import * as Dialog from "@radix-ui/react-dialog";
import {
  CheckCircleIcon,
  ClipboardTextIcon,
  CopyIcon,
  GavelIcon,
  MoonIcon,
  PackageIcon,
  PaperPlaneTiltIcon,
  PlusIcon,
  ReceiptIcon,
  RobotIcon,
  ShieldCheckIcon,
  SpinnerGapIcon,
  SunIcon,
  TruckIcon,
  WarningCircleIcon,
  XIcon,
} from "@phosphor-icons/react";
import { FormEvent, KeyboardEvent, useEffect, useMemo, useState } from "react";

type Role = "user" | "assistant";
type Phase = "missing_order_identifier" | "ready_to_check" | "processing" | "resolved";

type Message = {
  id: string;
  role: Role;
  content: string;
};

type Assessment = {
  case_id: string;
  assessment: { primary_issue: string; case_status: "action_required" | "no_action"; confidence: number };
  affected_entities: { order_ids: string[]; item_ids: string[]; seller_ids: string[]; payment_ids: string[] };
  root_cause_analysis: {
    ranked_causes: { cause_code: string; rank: number }[];
    responsible_parties: { party_type: string; party_id: string }[];
  };
  evidence_ids: string[];
  financial_resolution: {
    currency: string;
    item_total_brl: number;
    freight_total_brl: number;
    payment_total_brl: number;
    recommended_refund_brl: number;
  };
  resolution_actions: string[];
};

type ApiResponse = {
  reply: string;
  assessment?: Assessment;
  missing_fields?: string[];
  conversation_state?: { phase?: Phase; case_id?: string; claimed_order_id?: string };
  model_used?: string | null;
};

type ConversationState = {
  phase: Phase;
  caseId?: string;
  claimedOrderId?: string;
  intent?: string;
};

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
const CASE_ID = /\bEC_\d{3}\b/i;
const ORDER_ID = /\b[a-f0-9]{32}\b/i;

const INITIAL_MESSAGE: Message = {
  id: "welcome",
  role: "assistant",
  content: "Chào bạn. Hãy mô tả vấn đề bằng ngôn ngữ tự nhiên hoặc gửi mã case như EC_001 để mình kiểm tra.",
};

const ISSUE_LABELS: Record<string, string> = {
  canceled_order_paid: "Đơn hủy có thanh toán",
  unavailable_order_paid: "Đơn không khả dụng có thanh toán",
  late_delivery_seller: "Giao trễ do seller",
  late_delivery_logistics: "Giao trễ do vận chuyển",
  valid_split_payment: "Thanh toán tách hợp lệ",
  unsupported_late_claim: "Khiếu nại giao trễ không có căn cứ",
};

const AGENTS = [
  { label: "Đơn và seller", icon: PackageIcon },
  { label: "Thanh toán", icon: ReceiptIcon },
  { label: "Giao hàng", icon: TruckIcon },
  { label: "Policy", icon: GavelIcon },
  { label: "Kiểm chứng", icon: ShieldCheckIcon },
];

function newId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function formatMoney(value: number) {
  return new Intl.NumberFormat("vi-VN", { style: "currency", currency: "BRL", minimumFractionDigits: 2 }).format(value);
}

function inferIntent(message: string) {
  const lower = message.toLocaleLowerCase("vi-VN");
  if (lower.includes("trễ") || lower.includes("giao")) return "delivery_delay";
  if (lower.includes("thanh toán") || lower.includes("trừ tiền") || lower.includes("payment")) return "payment";
  if (lower.includes("hủy")) return "canceled_order";
  if (lower.includes("hoàn")) return "refund";
  return "general";
}

function loadConversationState(): ConversationState {
  try {
    const saved = sessionStorage.getItem("olist-conversation-state");
    return saved ? JSON.parse(saved) : { phase: "missing_order_identifier" };
  } catch {
    return { phase: "missing_order_identifier" };
  }
}

function StatusBadge({ status }: { status: "action_required" | "no_action" }) {
  const isAction = status === "action_required";
  return (
    <span className={isAction
      ? "inline-flex items-center gap-1.5 rounded-full border border-amber-300 bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
      : "inline-flex items-center gap-1.5 rounded-full border border-emerald-300 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200"}>
      {isAction ? <WarningCircleIcon size={14} weight="fill" /> : <CheckCircleIcon size={14} weight="fill" />}
      {isAction ? "Cần xử lý" : "Không cần hoàn tiền"}
    </span>
  );
}

function AgentPipeline({ processing }: { processing: boolean }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900" aria-label="Tiến trình các agent">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">Luồng kiểm chứng</p>
        <span className="text-xs text-slate-500 dark:text-slate-400">{processing ? "Đang xử lý" : "Sẵn sàng"}</span>
      </div>
      <ol className="grid grid-cols-5 gap-1">
        {AGENTS.map((agent) => {
          const Icon = agent.icon;
          return (
            <li key={agent.label} className="min-w-0 text-center">
              <span className={processing
                ? "mx-auto flex size-8 items-center justify-center rounded-lg bg-cyan-50 text-cyan-700 dark:bg-cyan-950/50 dark:text-cyan-300"
                : "mx-auto flex size-8 items-center justify-center rounded-lg bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400"}>
                {processing ? <SpinnerGapIcon size={17} className="animate-spin" /> : <Icon size={17} />}
              </span>
              <span className="mt-1 block truncate text-[10px] font-medium text-slate-500 dark:text-slate-400">{agent.label}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function CopyValue({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  };
  return (
    <button type="button" onClick={copy} className="group flex w-full items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-slate-600 transition-colors hover:bg-slate-100 active:translate-y-px dark:text-slate-300 dark:hover:bg-slate-800" aria-label={`Sao chép ${value}`}>
      <code className="min-w-0 truncate">{value}</code>
      {copied ? <CheckCircleIcon size={15} className="shrink-0 text-emerald-600" /> : <CopyIcon size={15} className="shrink-0 text-slate-400 group-hover:text-cyan-700" />}
    </button>
  );
}

function AuditContent({ assessment }: { assessment?: Assessment }) {
  if (!assessment) {
    return (
      <section className="rounded-xl border border-dashed border-slate-300 p-5 text-center dark:border-slate-700">
        <ClipboardTextIcon size={25} className="mx-auto text-slate-400" />
        <p className="mt-3 text-sm font-semibold text-slate-700 dark:text-slate-200">Chưa có kết quả kiểm chứng</p>
        <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">Kết quả policy, khoản hoàn và bằng chứng sẽ xuất hiện tại đây.</p>
      </section>
    );
  }
  const { assessment: decision, financial_resolution: money, root_cause_analysis: root, affected_entities: entities } = assessment;
  const parties = root.responsible_parties.length ? root.responsible_parties.map((party) => `${party.party_type}: ${party.party_id}`).join("\n") : "Không có bên chịu trách nhiệm hoàn tiền";
  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">Kết luận policy</p>
            <h2 className="mt-2 text-base font-semibold leading-6 text-slate-950 dark:text-white">{ISSUE_LABELS[decision.primary_issue] ?? decision.primary_issue}</h2>
          </div>
          <StatusBadge status={decision.case_status} />
        </div>
        <div className="mt-4 border-t border-slate-100 pt-4 dark:border-slate-800">
          <p className="text-xs font-medium text-slate-500 dark:text-slate-400">Khoản hoàn đề xuất</p>
          <p className="mt-1 text-3xl font-semibold tracking-tight text-slate-950 dark:text-white">{formatMoney(money.recommended_refund_brl)}</p>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">Action: {assessment.resolution_actions[0]}</p>
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">Đối soát</p>
        <dl className="mt-3 space-y-2 text-sm">
          <div className="flex justify-between gap-4"><dt className="text-slate-500 dark:text-slate-400">Sản phẩm</dt><dd className="font-medium text-slate-800 dark:text-slate-100">{formatMoney(money.item_total_brl)}</dd></div>
          <div className="flex justify-between gap-4"><dt className="text-slate-500 dark:text-slate-400">Freight</dt><dd className="font-medium text-slate-800 dark:text-slate-100">{formatMoney(money.freight_total_brl)}</dd></div>
          <div className="flex justify-between gap-4"><dt className="text-slate-500 dark:text-slate-400">Đã thanh toán</dt><dd className="font-medium text-slate-800 dark:text-slate-100">{formatMoney(money.payment_total_brl)}</dd></div>
        </dl>
        <p className="mt-4 whitespace-pre-line rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-600 dark:bg-slate-800/70 dark:text-slate-300">{parties}</p>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">Bằng chứng đã xác minh</p>
        <div className="mt-2 space-y-1">
          {assessment.evidence_ids.map((evidence) => <CopyValue key={evidence} value={evidence} />)}
        </div>
        <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">Order: {entities.order_ids[0] ?? "-"} · Độ tin cậy: {Math.round(decision.confidence * 100)}%</p>
      </section>
    </div>
  );
}

function EnrichmentCard({ onChoose }: { onChoose: (value: string) => void }) {
  return (
    <section className="rounded-xl border border-cyan-200 bg-cyan-50/60 p-4 dark:border-cyan-900 dark:bg-cyan-950/30">
      <div className="flex gap-3">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-100"><RobotIcon size={18} /></span>
        <div>
          <p className="text-sm font-semibold text-cyan-950 dark:text-cyan-50">Cần mã để kiểm tra chính xác</p>
          <p className="mt-1 text-sm leading-5 text-cyan-900/80 dark:text-cyan-100/75">Gửi mã case như EC_001 hoặc mã đơn Olist gồm 32 ký tự. Hệ thống không suy đoán dữ liệu còn thiếu.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" onClick={() => onChoose("Kiểm tra EC_001")} className="rounded-lg border border-cyan-300 bg-white px-3 py-1.5 text-xs font-semibold text-cyan-900 transition-colors hover:bg-cyan-100 active:translate-y-px dark:border-cyan-800 dark:bg-cyan-950 dark:text-cyan-100">Nhập mã case</button>
            <button type="button" onClick={() => onChoose("Tôi không có mã đơn")} className="rounded-lg border border-cyan-300 bg-transparent px-3 py-1.5 text-xs font-semibold text-cyan-900 transition-colors hover:bg-cyan-100 active:translate-y-px dark:border-cyan-800 dark:text-cyan-100">Tôi không có mã đơn</button>
          </div>
        </div>
      </div>
    </section>
  );
}

export function App() {
  const [messages, setMessages] = useState<Message[]>([INITIAL_MESSAGE]);
  const [draft, setDraft] = useState("");
  const [assessment, setAssessment] = useState<Assessment>();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [auditOpen, setAuditOpen] = useState(false);
  const [conversation, setConversation] = useState<ConversationState>(loadConversationState);

  useEffect(() => {
    sessionStorage.setItem("olist-conversation-state", JSON.stringify(conversation));
  }, [conversation]);

  const hasIdentifier = useMemo(() => CASE_ID.test(draft) || ORDER_ID.test(draft), [draft]);
  const needsIdentifier = conversation.phase === "missing_order_identifier" && !isLoading;

  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    const message = draft.trim();
    if (!message || isLoading) return;
    const userMessage: Message = { id: newId(), role: "user", content: message };
    const history = messages.map(({ role, content }) => ({ role, content }));
    setMessages((current) => [...current, userMessage]);
    setDraft("");
    setError(undefined);
    setIsLoading(true);
    setConversation((current) => ({ ...current, phase: hasIdentifier ? "processing" : "missing_order_identifier", intent: inferIntent(message) }));
    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, history }),
      });
      const data = await response.json() as ApiResponse;
      if (!response.ok) throw new Error(data.reply || "Không thể gửi yêu cầu.");
      setMessages((current) => [...current, { id: newId(), role: "assistant", content: data.reply }]);
      if (data.assessment) setAssessment(data.assessment);
      setConversation((current) => ({
        ...current,
        phase: data.conversation_state?.phase ?? (data.missing_fields?.length ? "missing_order_identifier" : "resolved"),
        caseId: data.conversation_state?.case_id ?? current.caseId,
        claimedOrderId: data.conversation_state?.claimed_order_id ?? current.claimedOrderId,
      }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Không thể kết nối backend.");
    } finally {
      setIsLoading(false);
    }
  };

  const submitFromKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  };

  const resetCase = () => {
    setMessages([INITIAL_MESSAGE]);
    setAssessment(undefined);
    setConversation({ phase: "missing_order_identifier" });
    setError(undefined);
  };

  return (
    <div className={theme === "dark" ? "dark" : ""}>
      <main className="min-h-[100dvh] bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
        <div className="mx-auto grid min-h-[100dvh] max-w-[1540px] xl:grid-cols-[250px_minmax(0,1fr)_348px]">
          <aside className="hidden border-r border-slate-200 bg-white px-4 py-5 dark:border-slate-800 dark:bg-slate-950 xl:flex xl:flex-col">
            <div className="flex items-center gap-3 px-2">
              <span className="flex size-9 items-center justify-center rounded-xl bg-cyan-700 text-white"><ShieldCheckIcon size={21} weight="fill" /></span>
              <div><p className="text-sm font-semibold">Olist</p><p className="text-xs text-slate-500 dark:text-slate-400">Dispute Assistant</p></div>
            </div>
            <button type="button" onClick={resetCase} className="mt-7 flex items-center justify-center gap-2 rounded-lg bg-cyan-700 px-3 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-cyan-800 active:translate-y-px"><PlusIcon size={17} /> Case mới</button>
            <nav className="mt-8" aria-label="Lịch sử case">
              <p className="px-2 text-xs font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">Gần đây</p>
              <button type="button" onClick={() => setDraft("Kiểm tra EC_001")} className="mt-3 flex w-full items-center gap-3 rounded-lg bg-slate-100 px-3 py-2.5 text-left text-sm font-medium text-slate-800 transition-colors hover:bg-slate-200 dark:bg-slate-900 dark:text-slate-100 dark:hover:bg-slate-800"><ClipboardTextIcon size={17} className="text-cyan-700" /> EC_001</button>
            </nav>
            <div className="mt-auto border-t border-slate-200 pt-4 dark:border-slate-800">
              <p className="text-xs text-slate-500 dark:text-slate-400">Nguồn dữ liệu</p>
              <p className="mt-1 text-sm font-medium">Olist CSV + EC_POLICY_V1</p>
            </div>
          </aside>

          <section className="flex min-h-[100dvh] min-w-0 flex-col">
            <header className="flex h-16 items-center justify-between border-b border-slate-200 bg-white px-4 dark:border-slate-800 dark:bg-slate-950 sm:px-6">
              <div className="flex min-w-0 items-center gap-3"><span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-cyan-700 text-white xl:hidden"><ShieldCheckIcon size={17} weight="fill" /></span><div className="min-w-0"><p className="truncate text-sm font-semibold">{conversation.caseId ?? "Case mới"}</p><p className="truncate text-xs text-slate-500 dark:text-slate-400">{conversation.claimedOrderId ?? "Chờ mã đơn hoặc mã case"}</p></div></div>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => setTheme((current) => current === "light" ? "dark" : "light")} className="flex size-9 items-center justify-center rounded-lg text-slate-600 transition-colors hover:bg-slate-100 active:translate-y-px dark:text-slate-300 dark:hover:bg-slate-800" aria-label="Đổi giao diện sáng tối">{theme === "light" ? <MoonIcon size={18} /> : <SunIcon size={18} />}</button>
                <Dialog.Root open={auditOpen} onOpenChange={setAuditOpen}><Dialog.Trigger asChild><button type="button" className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-100 active:translate-y-px dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800 xl:hidden">Kết quả</button></Dialog.Trigger><Dialog.Portal><Dialog.Overlay className="fixed inset-0 z-40 bg-slate-950/45" /><Dialog.Content className="fixed inset-x-0 bottom-0 z-50 max-h-[84dvh] overflow-y-auto rounded-t-xl bg-slate-50 p-5 shadow-2xl dark:bg-slate-950"><div className="mb-5 flex items-center justify-between"><Dialog.Title className="text-base font-semibold">Audit case</Dialog.Title><Dialog.Close asChild><button className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800" aria-label="Đóng"><XIcon size={19} /></button></Dialog.Close></div><AuditContent assessment={assessment} /></Dialog.Content></Dialog.Portal></Dialog.Root>
              </div>
            </header>

            <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-6">
              <div className="mx-auto max-w-3xl space-y-4">
                <AgentPipeline processing={isLoading} />
                {messages.map((message) => <article key={message.id} className={message.role === "user" ? "ml-auto max-w-[88%] rounded-xl bg-cyan-700 px-4 py-3 text-sm leading-6 text-white" : "max-w-[92%] whitespace-pre-wrap rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm leading-6 text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200"}>{message.content}</article>)}
                {isLoading && <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400" aria-live="polite"><SpinnerGapIcon size={18} className="animate-spin text-cyan-700" /> Các agent đang đối chiếu dữ liệu...</div>}
                {needsIdentifier && <EnrichmentCard onChoose={setDraft} />}
                {error && <div className="rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200"><p className="font-semibold">Không thể gửi yêu cầu</p><p className="mt-1">{error}</p><button type="button" onClick={() => void submit()} className="mt-3 rounded-lg border border-red-300 px-3 py-1.5 text-xs font-semibold hover:bg-red-100 dark:border-red-800 dark:hover:bg-red-900/40">Thử lại</button></div>}
              </div>
            </div>

            <form onSubmit={submit} className="border-t border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950 sm:px-6">
              <div className="mx-auto flex max-w-3xl items-end gap-3 rounded-xl border border-slate-300 bg-slate-50 p-2 focus-within:border-cyan-700 focus-within:ring-3 focus-within:ring-cyan-700/15 dark:border-slate-700 dark:bg-slate-900">
                <textarea value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={submitFromKey} rows={2} placeholder="Ví dụ: Đơn của tôi giao trễ, có được hoàn tiền không?" className="min-h-12 flex-1 resize-none bg-transparent px-2 py-1 text-sm leading-5 text-slate-800 placeholder:text-slate-400 focus:outline-none dark:text-slate-100" aria-label="Nhập câu hỏi" />
                <button type="submit" disabled={!draft.trim() || isLoading} className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-cyan-700 text-white transition-colors hover:bg-cyan-800 active:translate-y-px disabled:cursor-not-allowed disabled:bg-slate-300 dark:disabled:bg-slate-700" aria-label="Gửi câu hỏi"><PaperPlaneTiltIcon size={19} weight="fill" /></button>
              </div>
              <p className="mx-auto mt-2 max-w-3xl text-xs text-slate-500 dark:text-slate-400">{hasIdentifier ? "Đã nhận diện mã case hoặc mã đơn. Sẵn sàng kiểm tra." : "Bạn có thể hỏi tự nhiên. Hệ thống sẽ xin mã đơn khi cần."}</p>
            </form>
          </section>

          <aside className="hidden overflow-y-auto border-l border-slate-200 bg-slate-50 p-5 dark:border-slate-800 dark:bg-slate-950 xl:block"><p className="mb-4 text-xs font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">Kết quả kiểm chứng</p><AuditContent assessment={assessment} /></aside>
        </div>
      </main>
    </div>
  );
}
