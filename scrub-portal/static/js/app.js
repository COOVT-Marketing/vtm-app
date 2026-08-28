const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");
const fileNameEl = document.getElementById("file-name");
const processBtn = document.getElementById("process-btn");
const resultsSection = document.getElementById("results-section");
const loading = document.getElementById("loading");

let selectedFile = null;

function setFile(file) {
  if (!file) return;
  const valid = /\.(csv|xlsx|xls)$/i.test(file.name);
  if (!valid) {
    alert("Please select a CSV or Excel file.");
    return;
  }
  selectedFile = file;
  fileNameEl.textContent = file.name;
  processBtn.disabled = false;
}

dropZone.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", (e) => setFile(e.target.files[0]));

dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("dragover");
});

dropZone.addEventListener("dragleave", () => {
  dropZone.classList.remove("dragover");
});

dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("dragover");
  setFile(e.dataTransfer.files[0]);
});

processBtn.addEventListener("click", async () => {
  if (!selectedFile) return;

  const formData = new FormData();
  formData.append("file", selectedFile);

  resultsSection.classList.add("hidden");
  loading.classList.remove("hidden");
  processBtn.disabled = true;

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 180000); // 3 minutes

    const res = await fetch("/process", {
      method: "POST",
      body: formData,
      signal: controller.signal
    });

    clearTimeout(timeoutId);
    const data = await res.json();

    if (!data.success) {
      alert("Error: " + (data.error || "Unknown error"));
      return;
    }

    document.getElementById("good-count").textContent = data.good_count.toLocaleString();
    document.getElementById("bad-count").textContent = data.bad_count.toLocaleString();
    resultsSection.classList.remove("hidden");

  } catch (err) {
    if (err.name === "AbortError") {
      alert("The process is taking longer than expected. Please check the terminal and try again.");
    } else {
      alert("Network or server error: " + err.message);
    }
  } finally {
    loading.classList.add("hidden");
    processBtn.disabled = false;
  }
});
