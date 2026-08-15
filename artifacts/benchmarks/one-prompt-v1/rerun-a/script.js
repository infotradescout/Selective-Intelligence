const form = document.querySelector("#repair-form");
const result = document.querySelector("#request-result");
const summary = document.querySelector("#request-summary");
const copyButton = document.querySelector("#copy-request");
const editButton = document.querySelector("#edit-request");
const copyStatus = document.querySelector("#copy-status");

form.addEventListener("submit", (event) => {
  event.preventDefault();

  const data = new FormData(form);
  const item = String(data.get("item")).trim();
  const problem = String(data.get("problem")).trim();

  summary.textContent = [
    "REPAIR REQUEST",
    "",
    `Item: ${item}`,
    `Problem: ${problem}`,
    "",
    "Prepared locally — choose a verified service and contact method before sending."
  ].join("\n");

  copyStatus.textContent = "";
  form.hidden = true;
  result.hidden = false;
  result.focus();
});

copyButton.addEventListener("click", async () => {
  const requestText = summary.textContent;

  try {
    await navigator.clipboard.writeText(requestText);
    copyStatus.textContent = "Copied. The request is ready to paste into a message.";
  } catch {
    const range = document.createRange();
    const selection = window.getSelection();
    range.selectNodeContents(summary);
    selection.removeAllRanges();
    selection.addRange(range);
    copyStatus.textContent = "The request is selected. Copy it from the page.";
  }
});

editButton.addEventListener("click", () => {
  result.hidden = true;
  form.hidden = false;
  copyStatus.textContent = "";
  document.querySelector("#item").focus();
});
