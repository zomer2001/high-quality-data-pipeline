import type { FieldQuality } from "@/lib/researchDatabase";

const labels: Record<string, string> = { pass: "通过", fail: "未通过", unknown: "待核", not_applicable: "不适用" };

export default function QualityDetails({ quality }: { quality?: FieldQuality }) {
  if (!quality || quality.status === "legacy_unchecked") {
    return <p className="kh-validation-note">历史记录 · 尚未按本版规则核验</p>;
  }
  return <details className="kh-row-evidence"><summary>核验依据 · {quality.status === "blocked" ? "未通过" : "结构已检查，语义待核"}</summary>
    <ul>{quality.checks?.map((check, index) => <li key={index}><strong>{labels[check.result] ?? check.result}</strong> · {check.reason}</li>)}</ul>
    {!!quality.anchors?.length && <p>引文已绑定 {new Set(quality.anchors.map((anchor) => anchor.revision_id)).size} 个正文版本 · {quality.anchors.length} 处位置{quality.anchors.some((anchor) => anchor.ambiguous) ? "（含重复引文，需结合上下文）" : ""}</p>}
  </details>;
}
