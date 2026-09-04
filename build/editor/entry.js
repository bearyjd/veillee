// Veillee editor bundle entry. Milkdown Crepe, trimmed to a five-button toolbar.
import { Crepe } from "@milkdown/crepe";
import {
  toggleEmphasisCommand,
  toggleStrongCommand,
  turnIntoTextCommand,
  wrapInBlockquoteCommand,
  wrapInBulletListCommand,
  wrapInHeadingCommand,
} from "@milkdown/preset-commonmark";
import { callCommand } from "@milkdown/utils";
import "@milkdown/crepe/theme/common/style.css";
import "@milkdown/crepe/theme/frame.css";

const HEADING_LEVEL = 2;

export async function mount(root, initialMarkdown, onChange) {
  const crepe = new Crepe({
    root,
    defaultValue: initialMarkdown || "",
    features: {
      [Crepe.Feature.ImageBlock]: false,
      [Crepe.Feature.BlockEdit]: false,
      [Crepe.Feature.Table]: false,
      [Crepe.Feature.CodeMirror]: false,
      [Crepe.Feature.Latex]: false,
      [Crepe.Feature.LinkTooltip]: false,
      // Crepe's own toolbar only appears on selection and never became
      // visible in practice. Veillee renders its own, always-visible one.
      [Crepe.Feature.Toolbar]: false,
    },
  });
  await crepe.create();
  crepe.on((listener) => {
    listener.markdownUpdated(() => onChange());
  });

  const run = (command, payload) => {
    crepe.editor.action(callCommand(command.key, payload));
    // Put the cursor back where he was; a toolbar press must never steal focus.
    const box = root.querySelector('[contenteditable="true"]');
    if (box) box.focus();
    onChange();
  };

  const currentBlockIsHeading = () => {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) return false;
    let node = selection.anchorNode;
    while (node && node !== root) {
      if (node.nodeType === 1 && /^H[1-6]$/.test(node.tagName)) return true;
      node = node.parentNode;
    }
    return false;
  };

  return {
    getMarkdown: () => crepe.getMarkdown(),
    destroy: () => crepe.destroy(),
    bold: () => run(toggleStrongCommand),
    italic: () => run(toggleEmphasisCommand),
    // Pressing Heading on an existing heading takes it back to ordinary text,
    // so the button is never a one-way door.
    heading: () =>
      currentBlockIsHeading() ? run(turnIntoTextCommand) : run(wrapInHeadingCommand, HEADING_LEVEL),
    bulletList: () => run(wrapInBulletListCommand),
    quote: () => run(wrapInBlockquoteCommand),
  };
}
