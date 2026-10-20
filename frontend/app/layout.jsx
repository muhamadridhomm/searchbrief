import "./globals.css";

export const metadata = {
  title: "SearchBrief — source-grounded writing",
  description: "Turn your research into a useful, evidence-aware post draft.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
