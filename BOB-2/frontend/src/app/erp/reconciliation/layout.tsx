import BankStatementUploadFormatEnhancer from "./BankStatementUploadFormatEnhancer";

export default function ReconciliationLayout({ children }: any) {
  return (
    <>
      <BankStatementUploadFormatEnhancer />
      {children}
    </>
  );
}
