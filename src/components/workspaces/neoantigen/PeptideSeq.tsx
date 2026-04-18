import type { CSSProperties } from "react";

export default function PeptideSeq({
  seq,
  mutPos,
  style,
}: {
  seq: string;
  mutPos: number | null;
  style?: CSSProperties;
}) {
  return (
    <span style={style}>
      {seq.split("").map((ch, i) => {
        const isMut = mutPos !== null && i === mutPos;
        return (
          <span
            key={i}
            style={{
              color: isMut ? "var(--accent-ink)" : "inherit",
              background: isMut
                ? "color-mix(in oklch, var(--accent) 20%, transparent)"
                : "transparent",
              padding: isMut ? "1px 2px" : "0",
              borderRadius: 3,
              fontWeight: isMut ? 700 : "inherit",
            }}
          >
            {ch}
          </span>
        );
      })}
    </span>
  );
}
