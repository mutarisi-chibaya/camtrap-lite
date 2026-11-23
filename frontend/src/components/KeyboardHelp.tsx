const SHORTCUTS: [string, string][] = [
  ["1", "Animal"],
  ["2", "Empty"],
  ["3", "Person"],
  ["4", "Vehicle"],
  ["← / →", "Previous / next image in the event"],
  ["Z", "Undo the last decision"],
  ["?", "Show / hide this help"],
];

export default function KeyboardHelp({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-label="Keyboard shortcuts" onClick={(e) => e.stopPropagation()}>
        <h2>Keyboard shortcuts</h2>
        <table className="shortcuts">
          <tbody>
            {SHORTCUTS.map(([key, what]) => (
              <tr key={key}>
                <td>
                  <kbd>{key}</kbd>
                </td>
                <td>{what}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <button type="button" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}
