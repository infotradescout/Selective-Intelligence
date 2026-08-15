const form = document.querySelector("#repair-form");
const output = document.querySelector("#note-output");
const generatedNote = document.querySelector("#generated-note");
const copyButton = document.querySelector("#copy-note");
const copyStatus = document.querySelector("#copy-status");
const clearButton = document.querySelector("#clear-form");

function clean(value) {
  return value.trim().replace(/\s+/g, " ");
}

form.addEventListener("submit", (event) => {
  event.preventDefault();

  if (!form.reportValidity()) {
    return;
  }

  const data = new FormData(form);
  const item = clean(data.get("item"));
  const model = clean(data.get("model"));
  const symptom = clean(data.get("symptom"));
  const timing = data.get("timing");
  const context = clean(data.get("context"));

  const lines = [
    "REPAIR NOTE",
    "",
    `Item: ${item}`,
    model ? `Model / identifier: ${model}` : "Model / identifier: Not provided",
    `What changed: ${symptom}`,
    `When it began: ${timing}`,
    context ? `What happened just before: ${context}` : "What happened just before: Not known",
    "",
    "Please confirm the assessment, estimate process, and what needs my approval before work begins.",
  ];

  generatedNote.value = lines.join("\n");
  output.hidden = false;
  copyStatus.textContent = "";
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  output.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "nearest" });
});

copyButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(generatedNote.value);
    copyStatus.textContent = "Copied.";
  } catch (error) {
    generatedNote.focus();
    generatedNote.select();
    const copied = document.execCommand("copy");
    copyStatus.textContent = copied ? "Copied." : "Select the note and copy it manually.";
  }
});

clearButton.addEventListener("click", () => {
  form.reset();
  output.hidden = true;
  generatedNote.value = "";
  copyStatus.textContent = "";
  document.querySelector("#item").focus();
});
