"use strict";

const menu = document.querySelector(".menu-toggle");
const navigation = document.querySelector("#navigation");
if (menu && navigation) {
  menu.addEventListener("click", () => {
    const open = menu.getAttribute("aria-expanded") !== "true";
    menu.setAttribute("aria-expanded", String(open));
    navigation.classList.toggle("is-open", open);
  });
}

document.querySelectorAll(".answer-form").forEach((form) => {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button");
    const output = form.querySelector(".answer-result");
    if (button.disabled) return;
    button.disabled = true;
    button.textContent = "Проверяем…";
    output.className = "answer-result";
    output.textContent = "";
    try {
      const response = await fetch(form.dataset.api, {
        method: "POST",
        credentials: "same-origin",
        headers: {"Content-Type": "application/json", "X-CSRFToken": document.querySelector('meta[name="csrf-token"]').content},
        body: JSON.stringify({answer: form.elements.answer.value}),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Не удалось проверить ответ. Попробуйте снова.");
      output.classList.add(result.is_correct ? "result-success" : "result-error");
      output.textContent = result.message;
      document.querySelectorAll("[data-score]").forEach((counter) => { counter.textContent = result.score; });
      if (result.is_correct) {
        const card = form.closest(".task-card");
        card.classList.add("is-solved");
        card.querySelector(".solved-label").hidden = false;
        card.querySelector(".unsolved-label").hidden = true;
      }
    } catch (error) {
      output.classList.add("result-error");
      output.textContent = error instanceof TypeError
        ? "Нет связи с сервером. Проверьте, что приложение запущено, и попробуйте снова."
        : error.message;
    } finally {
      button.disabled = false;
      button.textContent = "Проверить";
    }
  });
});
