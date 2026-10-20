import { Navigate, Route, Routes } from "react-router-dom";
import Layout, { homePath } from "./components/Layout";
import VerificationsPage from "./pages/VerificationsPage";
import VerificationDetailPage from "./pages/VerificationDetailPage";
import DecisionsPage from "./pages/DecisionsPage";
import MyConsentsPage from "./pages/MyConsentsPage";
import ConsentRequestPage from "./pages/ConsentRequestPage";

export default function App() {
  return (
    <Routes>
      {/* Subject consent-giving screen — standalone, no admin chrome. */}
      <Route path="/consent/:requestId" element={<ConsentRequestPage />} />

      {/* Everything else lives inside the console shell. */}
      <Route element={<Layout />}>
        <Route index element={<Navigate to={homePath()} replace />} />
        <Route path="/verifications" element={<VerificationsPage />} />
        <Route path="/verifications/:id" element={<VerificationDetailPage />} />
        <Route path="/decisions" element={<DecisionsPage />} />
        <Route path="/my/consents" element={<MyConsentsPage />} />
        <Route path="*" element={<Navigate to={homePath()} replace />} />
      </Route>
    </Routes>
  );
}
