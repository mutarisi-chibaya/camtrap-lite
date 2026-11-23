import { NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import Export from "./pages/Export";
import Review from "./pages/Review";
import StaticCheck from "./pages/StaticCheck";
import Upload from "./pages/Upload";

const NAV = [
  { to: "/", label: "Dashboard" },
  { to: "/upload", label: "Upload" },
  { to: "/review", label: "Review" },
  { to: "/static", label: "Static Check" },
  { to: "/export", label: "Export" },
];

export default function App() {
  return (
    <>
      <header className="topbar">
        <span className="brand">CamTrap Lite</span>
        <nav>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end className={({ isActive }) => (isActive ? "active" : "")}>
              {n.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="app">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/review" element={<Review />} />
          <Route path="/static" element={<StaticCheck />} />
          <Route path="/export" element={<Export />} />
          <Route path="*" element={<p>Page not found.</p>} />
        </Routes>
      </main>
    </>
  );
}
