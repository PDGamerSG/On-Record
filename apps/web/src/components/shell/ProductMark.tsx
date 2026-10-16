/** The record glyph from the favicon: a disc whose grooves carry speaker colours, one arc per voice. */
export default function ProductMark({ size = 32 }: { size?: number }) {
  return (
    <svg className="mark" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <circle cx="16" cy="16" r="15.25" style={{ fill: "var(--surface-sunk)", stroke: "var(--line-strong)", strokeWidth: 1.5 }} />
      <g fill="none" strokeLinecap="round" strokeWidth="2.25">
        <path d="M16 4.5 A11.5 11.5 0 0 1 27.2 13.4" style={{ stroke: "var(--spk-0)" }} />
        <path d="M24.6 23.6 A11.5 11.5 0 0 1 9.2 25.3" style={{ stroke: "var(--spk-2)" }} />
        <path d="M8.2 11.1 A8.4 8.4 0 0 1 17.9 7.8" style={{ stroke: "var(--spk-1)" }} />
        <path d="M23.9 17.9 A8.4 8.4 0 0 1 19.6 23.6" style={{ stroke: "var(--spk-3)" }} />
      </g>
      <circle cx="16" cy="16" r="4.6" style={{ fill: "var(--ink)" }} />
      <circle cx="16" cy="16" r="1.2" style={{ fill: "var(--surface-sunk)" }} />
    </svg>
  );
}
