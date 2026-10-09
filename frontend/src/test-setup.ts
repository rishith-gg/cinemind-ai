import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";

// The default 1 s is too tight when the machine is busy (e.g. footage processing in parallel).
configure({ asyncUtilTimeout: 5000 });
