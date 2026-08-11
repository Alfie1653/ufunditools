let pollTimer = null;
let currentProductId = null;

function openCheckout(product_id) {
  currentProductId = product_id;
  document.getElementById("phone").value = "";
  document.getElementById("overlay").classList.add("open");
}

function closeCheckout() {
  document.getElementById("overlay").classList.remove("open");
  currentProductId = null;
}

function normalizePhone(raw) {
  let phone = raw.trim().replace(/\s+/g, "");
  if (phone.startsWith("+")) phone = phone.slice(1);
  if (phone.startsWith("0")) phone = "254" + phone.slice(1);
  return phone;
}
function setStatusTemporary(text, ms=5000) {
    setStatus(text);
    setTimeout(() => {
        if (document.getElementById("status").innerText === text) {
            setStatus("");
        }
    }, ms);
  }
  function setStatus(text) {
    const el = document.getElementById("status");
    el.innerText = text;
    if (text) {
      el.classList.add("visible");
    } else {
      el.classList.remove("visible");
    }
  }

function setButtonsDisabled(disabled) {
  document.querySelectorAll("button").forEach(btn => btn.disabled = disabled);
}

let currentPreviewImages = [];
let currentPreviewIndex = 0;

function openPreview(images, productName) {
  currentPreviewImages = images;
  currentPreviewIndex = 0;
  document.getElementById("preview-title").innerText = productName + " - Preview";
  setPreviewImage(currentPreviewIndex, null);
  document.getElementById("preview-overlay").classList.add("open");
}

function closePreview() {
  document.getElementById("preview-overlay").classList.remove("open");
}

function setPreviewImage(index, direction) {
  const img = document.getElementById("preview-image");

  document.getElementById("preview-counter").innerText =
    (index + 1) + " / " + currentPreviewImages.length;

  if (!direction) {
    // First load -- no animation, just set it
    img.src = "/static/images/previews/" + currentPreviewImages[index];
    return;
  }

  // Slide the current image out, then swap and slide the new one in
  img.classList.add(direction === "next" ? "slide-out-left" : "slide-out-right");

  setTimeout(() => {
    img.src = "/static/images/previews/" + currentPreviewImages[index];
    img.classList.remove("slide-out-left", "slide-out-right");
    img.classList.add(direction === "next" ? "slide-in-right" : "slide-in-left");

    setTimeout(() => {
      img.classList.remove("slide-in-right", "slide-in-left");
    }, 250);
  }, 200);
}

function nextPreviewImage() {
  if (currentPreviewIndex < currentPreviewImages.length - 1) {
    currentPreviewIndex++;
    setPreviewImage(currentPreviewIndex, "next");
  }
}

function prevPreviewImage() {
  if (currentPreviewIndex > 0) {
    currentPreviewIndex--;
    setPreviewImage(currentPreviewIndex, "prev");
  }
}



function openRequestModal() {
  document.getElementById("topic").value = "";
  document.getElementById("details").value = "";
  document.getElementById("contact").value = "";
  document.getElementById("request-status").innerText = "";
  document.getElementById("request-overlay").classList.add("open");
}

function closeRequestModal() {
  document.getElementById("request-overlay").classList.remove("open");
}

function submitRequest() {
  const topic = document.getElementById("topic").value.trim();
  const details = document.getElementById("details").value.trim();
  const contact = document.getElementById("contact").value.trim();
  const statusEl = document.getElementById("request-status");

  if (!topic) {
    statusEl.innerText = "Please enter a topic.";
    return;
  }

  statusEl.innerText = "Sending...";

  fetch("/request-note", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic, details, contact })
  })
    .then(res => res.json())
    .then(data => {
      statusEl.innerText = data.message;
      if (data.status === "ok") {
        setTimeout(closeRequestModal, 1800);
      }
    })
    .catch(() => {
      statusEl.innerText = "Something went wrong. Please try again.";
    });
}

function submitCheckout() {

  const phoneRaw = document.getElementById("phone").value;

  if (!phoneRaw) {
    setStatus("Enter your phone number first.");
    return;
  }

  const phone_number = normalizePhone(phoneRaw);
  const product_id = currentProductId;

  closeCheckout();

  setStatus("Sending payment request...");

  setButtonsDisabled(true);


  fetch("/buy", {

    method:"POST",

    headers:{
      "Content-Type":"application/json"
    },

    body:JSON.stringify({
      product:product_id,
      phone_number:phone_number
    })

  })


  .then(res=>res.json())


  .then(data=>{

    if(data.status==="error"){

      setStatus("Error: "+data.message);

      setButtonsDisabled(false);

      return;

    }


    setStatus(data.message || "Enter your M-Pesa PIN on your phone.");

    pollOrderStatus(data.token);


  })


  .catch(err=>{

    setStatus("Error: "+err);

    setButtonsDisabled(false);

  });

}



function pollOrderStatus(token){

let attempts=0;
const maxAttempts=40;

const interval=setInterval(()=>{

attempts++;

const isFinalAttempt = attempts >= maxAttempts;
const url = isFinalAttempt
  ? `/order-status/${token}?check=1`
  : `/order-status/${token}`;

fetch(url)
.then(res=>res.json())
.then(data=>{

if(data.status==="paid"){
  clearInterval(interval);
  setStatusTemporary("Payment confirmed! Redirecting. If you are not redirected, click the button below.");
  window.open(data.telegram_link, "_blank");
  setButtonsDisabled(false);

  const link = document.getElementById("telegram-link");
  link.href = data.telegram_link;
  link.style.display = "inline-block";
  link.scrollIntoView({ behavior: "smooth", block: "center" });

  setTimeout(() => {
    link.style.display = "none";
  }, 10000);
}

else if(data.status==="pending"){
  setStatus("Waiting for payment confirmation...");
  if(isFinalAttempt){
    clearInterval(interval);
    setStatus("Still waiting on payment. If you have paid, please message us on Telegram and we'll sort it out.");
    setButtonsDisabled(false);

    const link = document.getElementById("telegram-link");
    link.href = "https://t.me/UfundiToolsBot";
    link.textContent = "Message us on Telegram";
    link.style.display = "inline-block";
  }
}

else if(data.status==="failed"){
  clearInterval(interval);
  setStatus("Payment failed. Try again.");
  setButtonsDisabled(false);
}

})
.catch(()=>{
  clearInterval(interval);
  setStatus("Error checking payment status.");
});

},3000);

}


function openRecoverModal() {
  document.getElementById("recover-phone").value = "";
  document.getElementById("recover-status").innerText = "";
  document.getElementById("recover-overlay").classList.add("open");
}

function closeRecoverModal() {
  document.getElementById("recover-overlay").classList.remove("open");
}

function submitRecover() {
  const phoneRaw = document.getElementById("recover-phone").value;
  const statusEl = document.getElementById("recover-status");

  if (!phoneRaw) {
    statusEl.innerText = "Enter your phone number first.";
    return;
  }

  const phone_number = normalizePhone(phoneRaw);
  statusEl.innerText = "Searching...";

  fetch("/recover-link", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phone_number })
  })
    .then(res => res.json())
    .then(data => {
      if (data.status === "ok") {
        statusEl.innerText = "Order found! Opening Telegram...";
        window.open(data.telegram_link, "_blank");
        setTimeout(closeRecoverModal, 1500);
      } else {
        statusEl.innerText = data.message;
      }
    })
    .catch(() => {
      statusEl.innerText = "Something went wrong. Please try again.";
    });
}

function openSupportPanel() {
  document.getElementById("support-panel").classList.add("open");
}

function closeSupportPanel() {
  document.getElementById("support-panel").classList.remove("open");
}

function submitSupportMessage() {
  const message = document.getElementById("support-message").value.trim();
  const contact = document.getElementById("support-contact").value.trim();
  const statusEl = document.getElementById("support-status");

  if (!message) {
    statusEl.innerText = "Please enter a message.";
    return;
  }

  if (!contact) {
    statusEl.innerText = "Please provide a phone number or Telegram username.";
    return;
  }

  statusEl.innerText = "Sending...";

  fetch("/support-message", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, contact })
  })
    .then(res => res.json())
    .then(data => {
      statusEl.innerText = data.message;
      if (data.status === "ok") {
        document.getElementById("support-message").value = "";
        document.getElementById("support-contact").value = "";
        setTimeout(closeSupportPanel, 1800);
      }
    })
    .catch(() => {
      statusEl.innerText = "Something went wrong. Please try again.";
    });
}

let currentSort = "default";

function setSort(sortType, btn) {
  currentSort = sortType;
  document.querySelectorAll(".sort-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  updateProductDisplay();
}

function filterProducts() {
  updateProductDisplay();
}

function updateProductDisplay() {
  const searchInput = document.getElementById("search-input");
  const grid = document.getElementById("product-grid");

  if (!searchInput || !grid) return;
  const searchTerm = searchInput.value.trim().toLowerCase();
  const noResultsEl = document.getElementById("no-results");
  const items = Array.from(grid.children);

  let visibleCount = 0;

  items.forEach(item => {
    const name = item.querySelector(".description")?.innerText.toLowerCase() || "";
    const matches = name.includes(searchTerm);
    item.style.display = matches ? "" : "none";
    if (matches) visibleCount++;
  });

  if (searchTerm && visibleCount === 0) {
    document.getElementById("no-results-term").innerText = document.getElementById("search-input").value.trim();
    noResultsEl.style.display = "block";
    grid.style.display = "none";
    return;
  }

  noResultsEl.style.display = "none";
  grid.style.display = "grid";

  const visibleItems = items.filter(item => item.style.display !== "none");

  const isComingSoon = el => el.querySelector(".product-card")?.classList.contains("coming-soon") || false;

  let sorted;

  if (currentSort === "default") {
    sorted = visibleItems.slice().sort((a, b) => {
      const aComing = isComingSoon(a);
      const bComing = isComingSoon(b);
      if (aComing !== bComing) return  aComing ? 1 : -1; // different status -- buyable sinks below, coming-soon after
      // Both same status (both buyable , or coming-soon) --
      // sort by manual priority: items without a priority sink to the end of their group
      const priorityA = parseInt(a.getAttribute("data-priority") || "999");
      const priorityB = parseInt(b.getAttribute("data-priority") || "999");
      return priorityA - priorityB;
    });
  } else {
    sorted = visibleItems.slice().sort((a, b) => {
      if (currentSort === "name-asc") {
        const nameA = a.querySelector(".description")?.innerText.trim().toLowerCase() || "";
        const nameB = b.querySelector(".description")?.innerText.trim().toLowerCase() || "";
        return nameA.localeCompare(nameB);
      }

      const getPrice = el => {
        const text = el.querySelector(".price")?.innerText || "";
        const num = parseFloat(text.replace(/[^0-9.]/g, ""));
        return isNaN(num) ? Infinity : num;
      };

      const priceA = getPrice(a);
      const priceB = getPrice(b);

      return currentSort === "price-asc" ? priceA - priceB : priceB - priceA;
    });
  }

  sorted.forEach(item => grid.appendChild(item));
}

function openRequestModalWithTopic() {
  const searchTerm = document.getElementById("search-input").value.trim();
  openRequestModal();
  document.getElementById("topic").value = searchTerm;
}

function toggleFaq(button) {
  const answer = button.nextElementSibling;
  const isOpen = answer.classList.contains("open");

  document.querySelectorAll(".faq-answer.open").forEach(el => el.classList.remove("open"));
  document.querySelectorAll(".faq-question.active").forEach(el => el.classList.remove("active"));

  if (!isOpen) {
    answer.classList.add("open");
    button.classList.add("active");
  }
}