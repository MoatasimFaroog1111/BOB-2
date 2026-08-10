interface ManualEntryModalProps {
  language: string;
  closeLabel: string;
  value: string;
  isParsing: boolean;
  onChange: (value: string) => void;
  onClose: () => void;
  onParse: () => void;
}

export function ManualEntryModal({
  language,
  closeLabel,
  value,
  isParsing,
  onChange,
  onClose,
  onParse,
}: ManualEntryModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-md p-6 select-none">
      <div className="wood-panel rounded-[24px] border border-yellow-500/20 shadow-2xl w-full max-w-xl max-h-[85%] flex flex-col overflow-hidden">
        <div className="flex justify-between items-center px-6 py-4 border-b border-white/10 bg-black/40">
          <div className="flex flex-col">
            <h2 className="text-sm font-bold bg-gradient-to-r from-amber-300 to-yellow-500 bg-clip-text text-transparent">
              {language === "ar" ? "لصق مباشر أو كتابة يدوية للبيانات" : "Direct Paste or Manual Text Entry"}
            </h2>
            <p className="text-[10px] text-white/50 mt-0.5">
              {language === "ar"
                ? "الصق جدولاً من إكسيل أو اكتب تفاصيل القيود يدوياً وسيقوم النظام بفهمها ومطابقتها"
                : "Paste a table from Excel or type details line by line, and the system will parse and resolve them"}
            </p>
          </div>
          <button onClick={onClose} className="h-6 px-2.5 rounded-full border border-white/15 hover:border-white/30 text-white/60 hover:text-white text-[10px] font-bold cursor-pointer">
            {closeLabel}
          </button>
        </div>

        <div className="flex-1 p-6 flex flex-col gap-4 text-right" dir="rtl">
          <div className="text-[11px] text-[#d9a441] bg-[#d9a441]/10 border border-[#d9a441]/25 p-3.5 rounded-xl leading-relaxed">
            {language === "ar" ? (
              <>
                💡 <strong>طريقة الكتابة/اللصق:</strong>
                <ul className="list-disc list-inside mt-1.5 flex flex-col gap-1 pr-2">
                  <li>تستطيع لصق صفوف جدول من إكسيل مباشرة في المربع أدناه.</li>
                  <li>أو اكتب نصاً حراً مثل: <i>&quot;التاريخ: 2026-06-07، من حساب 101001 شريك شركة الرياض مدين 5000 إلى حساب 102014 دائن 5000&quot;</i>.</li>
                </ul>
              </>
            ) : (
              <>
                💡 <strong>Format Guide:</strong>
                <ul className="list-disc list-inside mt-1.5 flex flex-col gap-1 pl-2 text-left">
                  <li>You can paste table rows copied directly from Excel.</li>
                  <li>Or write free-text: <i>&quot;Date: 2026-06-07, Account 101001 debit 5000, Account 102014 credit 5000&quot;</i>.</li>
                </ul>
              </>
            )}
          </div>
          <textarea
            value={value}
            onChange={(event) => onChange(event.target.value)}
            placeholder={language === "ar" ? "الصق أو اكتب تفاصيل القيود والجداول هنا..." : "Paste or type journal details here..."}
            disabled={isParsing}
            className="w-full flex-1 min-h-[200px] bg-black/40 border border-white/15 focus:border-[#d9a441]/50 rounded-xl p-3.5 text-xs text-white focus:outline-none focus:ring-0 placeholder-white/20 resize-none font-mono text-right"
          />
        </div>

        <div className="px-6 py-4 bg-black/40 border-t border-white/10 flex justify-end gap-3">
          <button onClick={onClose} className="h-9 px-4 rounded-xl border border-white/15 hover:border-white/30 text-white/70 hover:text-white font-bold text-xs cursor-pointer transition-all">
            {language === "ar" ? "إلغاء" : "Cancel"}
          </button>
          <button
            onClick={onParse}
            disabled={isParsing || !value.trim()}
            className="h-9 px-5 rounded-xl bg-gradient-to-br from-[#221205] to-[#0f0701] border border-green-500 text-green-400 font-bold text-xs shadow-[0_0_12px_rgba(16,185,129,0.2)] hover:shadow-[0_0_20px_rgba(16,185,129,0.5)] transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
          >
            {isParsing ? (
              <>
                <svg className="animate-spin h-3.5 w-3.5 text-green-400" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
                <span>{language === "ar" ? "جاري التحليل..." : "Parsing..."}</span>
              </>
            ) : (
              <><span>🔍</span><span>{language === "ar" ? "تحليل وتوجيه البيانات" : "Parse & Route"}</span></>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
