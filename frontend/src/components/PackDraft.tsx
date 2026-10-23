import { useCallback, useState, type ReactNode } from 'react'

type Props = {
  id: string
  title: string
  description: string
  initialText: string
  downloadFileName: string
  /** Shown between the description and the text, e.g. where a Gemini draft came from. */
  children?: ReactNode
}

export function PackDraft({ id, title, description, initialText, downloadFileName, children }: Props) {
  const [text, setText] = useState(initialText)
  const [reviewed, setReviewed] = useState(false)
  const [copyNote, setCopyNote] = useState<string | null>(null)

  const onCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopyNote('Copied to clipboard.')
    } catch {
      setCopyNote('Could not copy — select the text and copy manually.')
    }
  }, [text])

  const onDownload = useCallback(() => {
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = downloadFileName
    a.click()
    URL.revokeObjectURL(url)
  }, [text, downloadFileName])

  return (
    <article className="card pack-draft" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>{title}</h2>
      <p className="subtle">{description}</p>
      {children}
      <label className="pack-draft-label" htmlFor={`${id}-textarea`}>Edit before you share</label>
      <textarea
        id={`${id}-textarea`}
        className="pack-textarea"
        rows={14}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <label className="pack-review">
        <input
          type="checkbox"
          checked={reviewed}
          onChange={(e) => setReviewed(e.target.checked)}
        />
        I&apos;ve reviewed this draft
      </label>
      <p className="cta-row pack-actions">
        <button type="button" className="btn" disabled={!reviewed} onClick={() => void onCopy()}>
          Copy
        </button>
        <button type="button" className="btn" disabled={!reviewed} onClick={onDownload}>
          Download .txt
        </button>
      </p>
      {copyNote && <p className="subtle">{copyNote}</p>}
    </article>
  )
}
