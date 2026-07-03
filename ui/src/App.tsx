import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import PartnersPage from "./pages/PartnersPage";
import PartnerOnboardPage from "./pages/PartnerOnboardPage";
import PartnerDetailPage from "./pages/PartnerDetailPage";
import MyConsentsPage from "./pages/MyConsentsPage";
import ConsentRequestPage from "./pages/ConsentRequestPage";

export default function App() {
  return (
    <Routes>
      {/* Subject consent-giving screen — standalone, no admin chrome. */}
      <Route path="/consent/:requestId" element={<ConsentRequestPage />} />

      {/* Everything else lives inside the console shell. */}
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/partners" replace />} />
        <Route path="/partners" element={<PartnersPage />} />
        <Route path="/partners/new" element={<PartnerOnboardPage />} />
        <Route path="/partners/:id" element={<PartnerDetailPage />} />
        <Route path="/my/consents" element={<MyConsentsPage />} />
        <Route path="*" element={<Navigate to="/partners" replace />} />
      </Route>
    </Routes>
  );
}
