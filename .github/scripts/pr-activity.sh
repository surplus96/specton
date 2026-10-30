#!/usr/bin/env bash
# PR 진행을 연결 이슈 댓글·실행 요약·Slack에 남긴다 (pr-activity 워크플로에서 실행, CONTRIBUTING "알림·기록").
#
# 환경 변수: GH_TOKEN, REPO(owner/name), PR, EVENT, ACTION, ACTOR,
#   REVIEW_STATE·REVIEW_URL(리뷰 제출 시), REQUESTED_REVIEWER(리뷰 요청 시),
#   SLACK_WEBHOOK_URL(선택), DRY_RUN=1(댓글·Slack 없이 메시지만 출력)
set -euo pipefail

: "${REPO:?}" "${PR:?}" "${EVENT:?}" "${ACTION:?}" "${ACTOR:?}"

pr_json=$(gh pr view "$PR" --repo "$REPO" \
  --json title,url,author,mergeCommit,additions,deletions,changedFiles,reviewRequests,closingIssuesReferences)
title=$(jq -r '.title' <<<"$pr_json")
url=$(jq -r '.url' <<<"$pr_json")
author=$(jq -r '.author.login' <<<"$pr_json")
size=$(jq -r '"파일 \(.changedFiles)개, +\(.additions) −\(.deletions)"' <<<"$pr_json")
issues=$(jq -r '.closingIssuesReferences[].number' <<<"$pr_json")

# 이벤트별 한 줄 기록. 기록할 필요가 없는 이벤트(댓글만 단 리뷰 등)는 조용히 끝낸다.
case "$EVENT/$ACTION" in
  pull_request/opened | pull_request/ready_for_review | pull_request/review_requested)
    reviewers=$(jq -r '[.reviewRequests[].login // empty | "@" + .] | join(" ")' <<<"$pr_json")
    if [[ -n "${REQUESTED_REVIEWER:-}" ]]; then reviewers="@$REQUESTED_REVIEWER"; fi
    line="🔎 **리뷰 요청** — [#$PR $title]($url) (작성 @$author → 리뷰 ${reviewers:-미지정}, $size)"
    ;;
  pull_request_review/submitted)
    case "${REVIEW_STATE:-}" in
      approved) verdict="✅ **승인**" ;;
      changes_requested) verdict="🔧 **변경 요청**" ;;
      *)
        echo "댓글만 단 리뷰(${REVIEW_STATE:-})는 기록하지 않습니다"
        exit 0
        ;;
    esac
    line="$verdict — [#$PR $title](${REVIEW_URL:-$url}) (리뷰 @$ACTOR → 작성 @$author)"
    ;;
  pull_request/closed)
    commit=$(jq -r '.mergeCommit.oid // empty' <<<"$pr_json")
    if [[ -n "$commit" ]]; then
      line="🚀 **병합** — [#$PR $title]($url) → \`main\` ${commit:0:7} (병합 @$ACTOR, 작성 @$author, $size)"
    else
      line="⏹ **병합 없이 닫힘** — [#$PR $title]($url) (닫음 @$ACTOR, 작성 @$author)"
    fi
    ;;
  *)
    echo "기록 대상이 아닌 이벤트입니다: $EVENT/$ACTION"
    exit 0
    ;;
esac

echo "$line"
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  echo "$line" >>"$GITHUB_STEP_SUMMARY"
fi
if [[ "${DRY_RUN:-}" == "1" ]]; then
  echo "[dry-run] 댓글 대상 이슈: ${issues:-없음}"
  exit 0
fi

# 연결 이슈 댓글: 이슈를 구독한 팀원과 멘션된 사람에게 GitHub 알림이 간다.
for issue in $issues; do
  gh issue comment "$issue" --repo "$REPO" --body "$line" >/dev/null
  echo "#$issue에 기록했습니다"
done

if [[ -n "${SLACK_WEBHOOK_URL:-}" ]]; then
  # Slack 링크 형식(<url|text>)으로 바꾸고 굵게 표시(**)는 *로 바꾼다
  slack_text=$(sed -E 's/\*\*/*/g; s/\[([^]]+)\]\(([^)]+)\)/<\2|\1>/g' <<<"$line")
  jq -n --arg text "$slack_text" '{text: $text}' \
    | curl --fail --silent --show-error -X POST -H 'Content-Type: application/json' --data @- "$SLACK_WEBHOOK_URL" >/dev/null
  echo "Slack에 보냈습니다"
fi
