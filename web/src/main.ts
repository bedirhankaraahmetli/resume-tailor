// App shell and hash router. Routes:
//   #/            new application        #/run/<id>      status, then result
//   #/presets     quick apply            #/folder/<path> files of one output folder
//   #/history     applications.csv       #/settings      repo, token, API keys

import "./style.css";
import { clear, errorText, h, notice } from "./dom";
import { github, settings } from "./store";
import type { View } from "./types";
import { showFolder } from "./views/folder";
import { showHistory } from "./views/history";
import { showNew } from "./views/new";
import { showPresets } from "./views/presets";
import { showRun } from "./views/run";
import { showSettings, showUnlock } from "./views/settings";

const NAV: [string, string][] = [
  ["#/", "New"],
  ["#/presets", "Quick apply"],
  ["#/history", "History"],
  ["#/settings", "Settings"],
];

const app = document.getElementById("app")!;
const nav = h("nav", { "aria-label": "Main" });
const main = h("main", { id: "main", tabindex: "-1" });
clear(app,
  h("a", { class: "skip", href: "#main", onclick: (e: Event) => {
    e.preventDefault();
    main.focus();
  } }, "Skip to content"),
  h("header", null, h("div", { class: "brand" }, "Resume Tailor"), nav),
  main);

let generation = 0;

function renderNav(route: string): void {
  clear(nav, NAV.map(([href, label]) => {
    const active = href === "#/" ? route === "" || route === "run" : href === `#/${route}`;
    return h("a", { href, "aria-current": active ? "page" : undefined }, label);
  }));
}

async function route(): Promise<void> {
  const gen = ++generation;
  const view: View = { el: main, alive: () => gen === generation };
  const [name = "", ...rest] = location.hash.replace(/^#\/?/, "").split("/");
  const arg = decodeURIComponent(rest.join("/"));
  renderNav(name);
  window.scrollTo(0, 0);

  if (name === "settings" || !settings()) {
    if (!settings()) renderNav("settings");
    showSettings(view);
    return;
  }
  const gh = github();
  if (!gh) {
    showUnlock(view, () => void route());
    return;
  }
  try {
    switch (name) {
      case "run":
        await showRun(view, gh, arg);
        break;
      case "folder":
        await showFolder(view, gh, arg);
        break;
      case "presets":
        await showPresets(view, gh);
        break;
      case "history":
        await showHistory(view, gh);
        break;
      default:
        showNew(view, gh);
    }
  } catch (e) {
    if (view.alive()) main.append(notice("error", errorText(e)));
  }
}

window.addEventListener("hashchange", () => void route());
void route();
