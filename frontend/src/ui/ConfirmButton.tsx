import { useId, useRef, type ComponentProps } from 'react'
import Button from './Button.tsx'

// 되돌릴 수 없는 행동(취소·중단·승인) 앞에 묻는 대화상자. <dialog>라 키보드(Esc)로 닫히고 포커스가 갇힌다.
type Props = Omit<ComponentProps<typeof Button>, 'onClick'> & {
  title: string
  description: string
  okText: string
  cancelText: string
  onConfirm: () => void
  danger?: boolean
}

function ConfirmButton({ title, description, okText, cancelText, onConfirm, danger, ...button }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const id = useId()
  return (
    <>
      <Button {...button} onClick={() => dialog.current?.showModal()} />
      <dialog ref={dialog} className="confirm" aria-labelledby={id} onClick={(e) => e.target === dialog.current && dialog.current?.close()}>
        <h2 id={id}>{title}</h2>
        <p>{description}</p>
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <Button variant="secondary" onClick={() => dialog.current?.close()}>
            {cancelText}
          </Button>
          <Button
            variant={danger ? 'danger' : 'primary'}
            onClick={() => {
              dialog.current?.close()
              onConfirm()
            }}
          >
            {okText}
          </Button>
        </div>
      </dialog>
    </>
  )
}

export default ConfirmButton
