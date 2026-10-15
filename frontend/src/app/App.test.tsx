import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, vi } from "vitest";

import { client } from "../api/client.gen";
import { createQueryClient } from "../lib/queryClient";
import { useToasts } from "../lib/toast";
import { App } from "./App";

interface P {
  id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
}
let projects: P[] = [];

/** Tiny fake of the backend's project API. */
function fakeBackend() {
  return vi.fn(async (input: Request | string | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(new URL(String(input), "http://localhost"), init);
    const url = new URL(req.url);
    if (url.pathname === "/api/projects" && req.method === "GET") return Response.json(projects);
    if (url.pathname === "/api/projects" && req.method === "POST") {
      const body = (await req.json()) as { name: string };
      if (body.name === "boom")
        return Response.json({ code: "invalid_input", message: "That name is reserved." }, { status: 422 });
      const p = { id: "a".repeat(32), name: body.name, description: "", created_at: "", updated_at: "" };
      projects.push(p);
      return Response.json(p, { status: 201 });
    }
    const m = /^\/api\/projects\/(\w+)$/.exec(url.pathname);
    if (m && req.method === "GET") {
      const p = projects.find((x) => x.id === m[1]);
      return p ? Response.json(p) : Response.json({ code: "not_found", message: "That project does not exist." }, { status: 404 });
    }
    if (m && req.method === "DELETE") {
      projects = projects.filter((x) => x.id !== m[1]);
      return new Response(null, { status: 204 });
    }
    return Response.json({}, { status: 404 });
  });
}

function renderApp(path = "/projects") {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  projects = [];
  client.setConfig({ baseUrl: "http://localhost" });
  vi.stubGlobal("fetch", fakeBackend());
  useToasts.setState({ toasts: [] });
});
afterEach(() => vi.unstubAllGlobals());

it("shows an empty state, then creates and opens a project", async () => {
  renderApp();
  expect(await screen.findByText("No projects yet", { selector: "p" })).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Project name"), "Short film");
  await userEvent.click(screen.getByRole("button", { name: "Create project" }));
  expect(await screen.findByRole("heading", { name: "Short film" })).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("Created project");
  expect(within(screen.getByRole("navigation", { name: "Main" })).getByText("Library")).toBeInTheDocument();
});

it("shows the backend's plain-language error as a toast", async () => {
  renderApp();
  await screen.findByLabelText("Project name");
  await userEvent.type(screen.getByLabelText("Project name"), "boom");
  await userEvent.click(screen.getByRole("button", { name: "Create project" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("That name is reserved.");
});

it("deletes a project after confirmation", async () => {
  projects = [{ id: "b".repeat(32), name: "Old", description: "", created_at: "", updated_at: "" }];
  vi.spyOn(window, "confirm").mockReturnValue(true);
  renderApp();
  await userEvent.click(await screen.findByRole("button", { name: "Delete Old" }));
  await waitFor(() => expect(screen.queryByText("Old", { selector: "a" })).not.toBeInTheDocument());
});

it("shows a not-found state for an unknown project", async () => {
  renderApp("/projects/" + "c".repeat(32));
  expect(await screen.findByRole("alert")).toHaveTextContent("That project does not exist.");
});

it("opens the Timeline page, which asks for a project first", async () => {
  renderApp("/timeline");
  expect(await screen.findByText("No project selected")).toBeInTheDocument();
  expect(screen.getByText(/to build a rough cut/)).toBeInTheDocument();
});
