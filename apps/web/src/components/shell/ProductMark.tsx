/** The record glyph from the favicon: a black disc whose grooves carry speaker colours, one arc per voice. */
export default function ProductMark({ size = 32 }: { size?: number }) {
  return (
    <svg className="mark" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <circle cx="16" cy="16" r="16" fill="#15171c" />
      <circle cx="16" cy="16" r="13.6" fill="none" stroke="#ffffff" strokeOpacity="0.08" strokeWidth="0.75" />
      <g fill="none" strokeLinecap="round" strokeWidth="2.4">
        <path d="M16 4.5 A11.5 11.5 0 0 1 27.2 13.4" stroke="#6b95ff" />
        <path d="M24.6 23.6 A11.5 11.5 0 0 1 9.2 25.3" stroke="#f2b53a" />
        <path d="M8.2 11.1 A8.4 8.4 0 0 1 17.9 7.8" stroke="#2cc4a8" />
        <path d="M23.9 17.9 A8.4 8.4 0 0 1 19.6 23.6" stroke="#ef72bf" />
      </g>
      <circle cx="16" cy="16" r="4.4" fill="#f6f5f2" />
      <circle cx="16" cy="16" r="1.15" fill="#15171c" />
    </svg>
  );
}
