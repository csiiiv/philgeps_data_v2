import { useCallback, useEffect, useState } from 'react';

/**
 * Layered modal navigation: researcher drill-downs push onto a stack so
 * going "back" restores the previous view exactly. Escape / Back / ✕ all
 * pop one layer. "Close all" only appears on deep stacks and needs a
 * confirm click.
 *
 * Critical click-safety: only the topmost backdrop is clickable. Behind
 * layers use pointer-events:none so a Back/✕ click cannot fall through
 * onto the newly revealed backdrop and double-pop the stack.
 */
export type ModalLayer =
  | { kind: 'process'; processId: string }
  | { kind: 'party'; name: string }
  | {
      kind: 'records';
      releaseId: string;
      dataset: string;
      /** When set, show only this one record (e.g. one award from a timeline stop). */
      recordId?: string;
      /** Human label for the focused record, e.g. "Award: Accommodation". */
      focusLabel?: string;
    }
  | { kind: 'sources'; releaseId: string }
  | { kind: 'sourceRows'; sourceFileId: string; startRow: number; endRow: number; fileName?: string };

export function useModalStack() {
  const [layers, setLayers] = useState<ModalLayer[]>([]);

  const push = useCallback((layer: ModalLayer) => {
    setLayers((stack) => [...stack, layer]);
  }, []);

  const pop = useCallback(() => {
    setLayers((stack) => stack.slice(0, -1));
  }, []);

  const closeAll = useCallback(() => setLayers([]), []);

  const isOpen = useCallback(
    (kind: ModalLayer['kind']) => layers.some((l) => l.kind === kind),
    [layers],
  );

  /** Push a process layer, or move it to the top if already in the stack. */
  const openProcess = useCallback((processId: string) => {
    setLayers((stack) => {
      const rest = stack.filter((l) => !(l.kind === 'process' && l.processId === processId));
      return [...rest, { kind: 'process', processId }];
    });
  }, []);

  /** Reset the stack to exactly one process layer (deep link / trace box). */
  const resetToProcess = useCallback((processId: string) => {
    setLayers([{ kind: 'process', processId }]);
  }, []);

  return { layers, push, pop, closeAll, isOpen, openProcess, resetToProcess };
}

export default function ModalHost({
  layers,
  pop,
  renderLayer,
}: {
  layers: ModalLayer[];
  pop: () => void;
  renderLayer: (layer: ModalLayer, depth: number, isActive: boolean) => React.ReactNode;
}) {
  useEffect(() => {
    if (layers.length === 0) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        pop();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [layers.length, pop]);

  if (layers.length === 0) return null;
  const top = layers.length - 1;
  return (
    <>
      {layers.map((layer, index) => {
        const isTop = index === top;
        return (
          <div
            key={`${layer.kind}-${index}-${JSON.stringify(layer)}`}
            className={`layer-backdrop ${isTop ? '' : 'behind'}`}
            style={{ zIndex: 50 + index }}
            // Only the topmost backdrop dismisses on outside click.
            // Behind layers must not receive clicks — otherwise Back/✕
            // on the top layer falls through and double-pops.
            onClick={isTop ? pop : undefined}
          >
            {renderLayer(layer, index, isTop)}
          </div>
        );
      })}
    </>
  );
}

export function ModalHeader({
  title,
  depth,
  total,
  onBack,
  onClose,
  onCloseAll,
}: {
  title: React.ReactNode;
  depth: number;
  total: number;
  onBack: () => void;
  onClose: () => void;
  onCloseAll: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  useEffect(() => {
    setConfirming(false);
  }, [depth, total]);

  // Always stopPropagation so header actions never bubble to the backdrop.
  const safe = (action: () => void) => (event: React.MouseEvent) => {
    event.stopPropagation();
    event.preventDefault();
    action();
  };

  return (
    <div className="inspector-head" onClick={(e) => e.stopPropagation()}>
      <strong className="modal-title">
        {depth > 0 && (
          <button
            type="button"
            className="secondary back-button"
            onClick={safe(onBack)}
            aria-label="Back to previous view"
          >
            ← Back
          </button>
        )}
        {title}
      </strong>
      <span className="modal-close-group">
        {total > 1 && (
          <button
            type="button"
            className={`secondary close-all-button ${confirming ? 'armed' : ''}`}
            onClick={(event) => {
              event.stopPropagation();
              event.preventDefault();
              if (confirming) onCloseAll();
              else setConfirming(true);
            }}
            onBlur={() => setConfirming(false)}
            title="Close every open layer and return to the page"
          >
            {confirming ? 'Close all — sure?' : 'Close all'}
          </button>
        )}
        <button
          type="button"
          className="secondary close-button"
          onClick={safe(onClose)}
          aria-label="Close this view"
        >
          ✕
        </button>
      </span>
    </div>
  );
}
