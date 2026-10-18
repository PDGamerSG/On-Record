import { StrictMode } from "react";
import { IconContext } from "@phosphor-icons/react";
import { createRoot } from "react-dom/client";
import "./styles/tokens.css";
import "./styles/base.css";
import App from "./App";
import { resolveMode } from "./api/mode";

void resolveMode().then(() => {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      {/* icons are 24px unless a stylesheet sizes them; weight changes mark state (regular, fill when active) */}
      <IconContext.Provider value={{ size: 24, weight: "regular" }}>
        <App />
      </IconContext.Provider>
    </StrictMode>,
  );
});
