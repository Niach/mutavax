import { Card, CardHead } from "@/components/ui-kit";

export default function ExpertDrawer({
  commandLog,
  pvacseqVersion,
}: {
  commandLog: string[];
  pvacseqVersion: string | null;
}) {
  if (commandLog.length === 0) return null;
  return (
    <Card style={{ marginTop: 20 }}>
      <CardHead
        eyebrow="Expert · pVACseq command"
        title={pvacseqVersion ?? "NetMHCpan 4.1 + NetMHCIIpan 4.3"}
      />
      <pre
        style={{
          margin: 0,
          padding: "16px 22px",
          fontFamily: "var(--font-mono)",
          fontSize: 12,
          lineHeight: 1.7,
          color: "var(--muted)",
          background: "var(--surface-sunk)",
          borderBottomLeftRadius: "var(--radius-lg)",
          borderBottomRightRadius: "var(--radius-lg)",
          overflow: "auto",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {commandLog.map((line) => `$ ${line}`).join("\n\n")}
      </pre>
    </Card>
  );
}
