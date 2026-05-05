import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

// jsdom does not implement scrollIntoView; mock it globally for tests that render
// components using refs with scrollIntoView (e.g. LiveConsole).
Element.prototype.scrollIntoView = vi.fn();
