// Veillee editor bundle entry. Milkdown Crepe, trimmed to a five-button toolbar.
import { Crepe } from "@milkdown/crepe";
import "@milkdown/crepe/theme/common/style.css";
import "@milkdown/crepe/theme/frame.css";

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
    },
  });
  await crepe.create();
  crepe.on((listener) => {
    listener.markdownUpdated(() => onChange());
  });
  return {
    getMarkdown: () => crepe.getMarkdown(),
    destroy: () => crepe.destroy(),
  };
}
