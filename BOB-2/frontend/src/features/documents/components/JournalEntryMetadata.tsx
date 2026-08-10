import type { Dispatch, SetStateAction } from "react";

import type { OdooJournal } from "@/features/documents/model/types";

interface JournalEntryMetadataProps {
  language: string;
  date: string;
  setDate: Dispatch<SetStateAction<string>>;
  reference: string;
  setReference: Dispatch<SetStateAction<string>>;
  journals: OdooJournal[];
  selectedJournalId: number | null;
  setSelectedJournalId: Dispatch<SetStateAction<number | null>>;
}

export function JournalEntryMetadata({
  language, date, setDate, reference, setReference,
  journals, selectedJournalId, setSelectedJournalId,
}: JournalEntryMetadataProps) {
  return (
    <div className="grid grid-cols-3 gap-3">
      <div className="flex flex-col gap-1">
        <label className="text-[10px] text-white/50 font-semibold">{language === "ar" ? "التاريخ" : "Date"}</label>
        <input type="date" value={date} onChange={(event) => setDate(event.target.value)} className="w-full bg-black/40 border border-white/10 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-amber-500/50 focus:ring-0" />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-[10px] text-white/50 font-semibold">{language === "ar" ? "رقم المرجع" : "Reference"}</label>
        <input type="text" value={reference} onChange={(event) => setReference(event.target.value)} placeholder={language === "ar" ? "رقم القيد..." : "Entry ref..."} className="w-full bg-black/40 border border-white/10 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-amber-500/50 focus:ring-0 placeholder-white/25" />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-[10px] text-white/50 font-semibold">{language === "ar" ? "اليومية" : "Journal"}</label>
        <select value={selectedJournalId || ""} onChange={(event) => setSelectedJournalId(event.target.value ? parseInt(event.target.value) : null)} className="w-full bg-black/40 border border-white/10 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-amber-500/50 focus:ring-0">
          {journals.map((journal) => <option key={journal.id} value={journal.id} className="bg-[#1b0d04] text-white">{journal.name} ({journal.code})</option>)}
        </select>
      </div>
    </div>
  );
}
