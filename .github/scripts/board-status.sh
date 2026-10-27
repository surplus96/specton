#!/usr/bin/env bash
# 프로젝트 보드 카드의 Status를 바꾼다 (board-status 워크플로에서 실행, CONTRIBUTING "작업 흐름").
#
# 사용: board-status.sh <이슈·PR 번호> <바꿀 Status> [이 상태일 때만 바꿈...]
#   board-status.sh 12 "In Progress" Backlog Todo   # Backlog·Todo일 때만 In Progress로
#   board-status.sh 64 "In Review"                   # 현재 상태와 무관하게 In Review로
#
# 환경 변수: GH_TOKEN(project 권한), OWNER, PROJECT_NUMBER, REPO(owner/name), DRY_RUN=1(바꾸지 않고 출력만)
set -euo pipefail

number="$1"
target="$2"
shift 2
allowed_from=("$@")

: "${OWNER:?}" "${PROJECT_NUMBER:?}" "${REPO:?}"
ATTEMPTS="${ATTEMPTS:-6}"
WAIT_SECONDS="${WAIT_SECONDS:-10}"

project_json=$(gh api graphql -F owner="$OWNER" -F number="$PROJECT_NUMBER" -f query='
  query($owner: String!, $number: Int!) {
    user(login: $owner) {
      projectV2(number: $number) {
        id
        field(name: "Status") { ... on ProjectV2SingleSelectField { id options { id name } } }
      }
    }
  }')
project_id=$(jq -r '.data.user.projectV2.id' <<<"$project_json")
field_id=$(jq -r '.data.user.projectV2.field.id' <<<"$project_json")
option_id=$(jq -r --arg t "$target" '.data.user.projectV2.field.options[] | select(.name == $t) | .id' <<<"$project_json")
if [[ -z "$option_id" ]]; then
  echo "::error::보드에 '$target' 상태가 없습니다"
  exit 1
fi

# 보드 카드와 현재 상태. 새 PR은 보드에 늦게 들어오고 기본 자동화가 Backlog로 정하므로,
# 카드가 생기고 상태가 정해질 때까지 기다린 뒤 바꾼다 (기본 자동화가 덮어쓰지 않도록).
find_item() {
  gh api graphql -F owner="${REPO%/*}" -F name="${REPO#*/}" -F number="$number" -f query='
    query($owner: String!, $name: String!, $number: Int!) {
      repository(owner: $owner, name: $name) {
        issueOrPullRequest(number: $number) {
          ... on Issue { projectItems(first: 20) { nodes { id project { id }
            status: fieldValueByName(name: "Status") { ... on ProjectV2ItemFieldSingleSelectValue { name } } } } }
          ... on PullRequest { projectItems(first: 20) { nodes { id project { id }
            status: fieldValueByName(name: "Status") { ... on ProjectV2ItemFieldSingleSelectValue { name } } } } }
        }
      }
    }' | jq -c --arg p "$project_id" '.data.repository.issueOrPullRequest.projectItems.nodes[] | select(.project.id == $p)'
}

item=""
for ((attempt = 1; attempt <= ATTEMPTS; attempt++)); do
  item=$(find_item)
  if [[ -n "$item" && "$(jq -r '.status.name // empty' <<<"$item")" != "" ]]; then
    break
  fi
  item=""
  sleep "$WAIT_SECONDS"
done
if [[ -z "$item" ]]; then
  echo "::warning::#$number 카드가 보드에 없거나 상태가 정해지지 않아 건너뜁니다"
  exit 0
fi

item_id=$(jq -r '.id' <<<"$item")
current=$(jq -r '.status.name' <<<"$item")
if [[ "$current" == "$target" ]]; then
  echo "#$number 이미 $target"
  exit 0
fi
if ((${#allowed_from[@]} > 0)) && [[ ! " ${allowed_from[*]} " == *" $current "* ]]; then
  echo "#$number 현재 $current — ${allowed_from[*]}일 때만 바꾸므로 그대로 둡니다"
  exit 0
fi
if [[ "${DRY_RUN:-}" == "1" ]]; then
  echo "[dry-run] #$number $current → $target"
  exit 0
fi

gh api graphql -F project="$project_id" -F item="$item_id" -F field="$field_id" -F option="$option_id" -f query='
  mutation($project: ID!, $item: ID!, $field: ID!, $option: String!) {
    updateProjectV2ItemFieldValue(input: {
      projectId: $project, itemId: $item, fieldId: $field, value: { singleSelectOptionId: $option }
    }) { projectV2Item { id } }
  }' >/dev/null
echo "#$number $current → $target"
