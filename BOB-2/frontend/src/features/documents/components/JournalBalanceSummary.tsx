interface JournalBalanceSummaryProps {
  language: string;
  totalDebit: number;
  totalCredit: number;
  isBalanced: boolean;
}

export function JournalBalanceSummary({ language, totalDebit, totalCredit, isBalanced }: JournalBalanceSummaryProps) {
  return (
    <div className="flex justify-between items-center bg-black/20 p-3 border border-white/5 rounded-xl text-xs">
      <div className="flex gap-4">
        <div><span className="text-white/40">{language === "ar" ? "إجمالي المدين:" : "Total Debit:"} </span><span className="font-mono font-bold text-yellow-500">{totalDebit.toLocaleString()} ر.س</span></div>
        <div><span className="text-white/40">{language === "ar" ? "إجمالي الدائن:" : "Total Credit:"} </span><span className="font-mono font-bold text-yellow-500">{totalCredit.toLocaleString()} ر.س</span></div>
      </div>
      <div className="flex items-center gap-1.5">
        {isBalanced ? (
          <><span className="status-dot" /><span className="text-[10.5px] text-emerald-400 font-bold">{language === "ar" ? "قيد متزن" : "Balanced"}</span></>
        ) : (
          <><span className="w-2.5 h-2.5 rounded-full bg-red-500 shadow-[0_0_10px_rgba(239,68,68,0.8)]" /><span className="text-[10.5px] text-red-400 font-bold">{language === "ar" ? "غير متزن" : "Unbalanced"}</span></>
        )}
      </div>
    </div>
  );
}
