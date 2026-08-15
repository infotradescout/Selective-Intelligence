const form = document.querySelector("#repair-form");
const result = document.querySelector("#result");
const note = document.querySelector("#repair-note");
const copyButton = document.querySelector("#copy-note");
const editButton = document.querySelector("#edit-note");
const copyStatus = document.querySelector("#copy-status");

form.addEventListener("submit", (event) => {
  event.preventDefault();

  const data = new FormData(form);
  const item = data.get("item").trim();
  const symptom = data.get("symptom");
  const details = data.get("details").trim();
  const timing = data.get("timing");

  note.textContent = [
    "REPAIR REQUEST",
    "",
    `Item: ${item}`,
    `Problem: ${symptom}`,
    `What I noticed: ${details}`,
    `Timing: ${timing}`,
  ].join("\n");

  form.hidden = true;
  result.hidden = false;
  copyStatus.textContent = "";
  result.querySelector("h2").focus({ preventScroll: true });
  result.scrollIntoView({ behavior: "smooth", block: "nearest" });
});

copyButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(note.textContent);
    copyStatus.textContent = "Copied. You can paste this into a text or email.";
  } catch {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(note);
    selection.removeAllRanges();
    selection.addRange(range);
    copyStatus.textContent = "The note is selected. Use Ctrl+C or Command+C to copy it.";
  }
});

editButton.addEventListener("click", () => {
  result.hidden = true;
  form.hidden = false;
  document.querySelector("#item").focus({ preventScroll: true });
  form.scrollIntoView({ behavior: "smooth", block: "nearest" });
});
