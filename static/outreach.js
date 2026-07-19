(() => {
  const companyList = document.getElementById("company-list");
  const peopleList = document.getElementById("people-list");
  const peopleTitle = document.getElementById("people-title");
  const companyFilter = document.getElementById("company-filter");
  const statusFilter = document.getElementById("status-filter");
  const btnSync = document.getElementById("btn-sync");
  const btnGenBatch = document.getElementById("btn-gen-batch");
  const editorEmpty = document.getElementById("editor-empty");
  const draftForm = document.getElementById("draft-form");
  const draftStatus = document.getElementById("draft-status");
  const draftMsg = document.getElementById("draft-msg");
  const fieldTo = document.getElementById("field-to");
  const fieldSubject = document.getElementById("field-subject");
  const fieldBody = document.getElementById("field-body");
  const fieldNotes = document.getElementById("field-notes");
  const subjectOptions = document.getElementById("subject-options");

  let selectedCompany = "";
  let selectedEmail = "";

  function renderSubjects(options, active) {
    const list = options || [];
    if (!list.length) {
      subjectOptions.hidden = true;
      subjectOptions.innerHTML = "";
      return;
    }
    subjectOptions.hidden = false;
    subjectOptions.innerHTML = list
      .map(
        (s) =>
          `<button type="button" class="subject-chip${s === active ? " active" : ""}" data-subject="${escapeAttr(s)}">${escapeHtml(s)}</button>`
      )
      .join("");
  }

  subjectOptions.addEventListener("click", (e) => {
    const btn = e.target.closest(".subject-chip");
    if (!btn) return;
    fieldSubject.value = btn.dataset.subject;
    [...subjectOptions.querySelectorAll(".subject-chip")].forEach((b) =>
      b.classList.toggle("active", b === btn)
    );
  });

  function showMsg(text, kind = "") {
    draftMsg.hidden = !text;
    draftMsg.textContent = text || "";
    draftMsg.className = "msg" + (kind ? ` ${kind}` : "");
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail;
      const msg = Array.isArray(detail)
        ? detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
        : detail || data.error || res.statusText;
      throw new Error(msg);
    }
    return data;
  }

  function renderCompanies(rows) {
    companyList.innerHTML = rows
      .map(
        (c) => `<li>
      <button type="button" class="company-btn${c.company === selectedCompany ? " active" : ""}" data-company="${escapeAttr(c.company)}">
        <span class="co-name">${escapeHtml(c.company)}</span>
        <span class="co-meta">${c.total} · ${c.sent} sent · ${c.drafted} drafted</span>
      </button>
    </li>`
      )
      .join("");
  }

  function renderPeople(rows) {
    if (!rows.length) {
      peopleList.innerHTML = `<li class="hint">No contacts for this filter.</li>`;
      return;
    }
    peopleList.innerHTML = rows
      .map(
        (p) => `<li>
      <button type="button" class="person-btn${p.email === selectedEmail ? " active" : ""}" data-email="${escapeAttr(p.email)}">
        <span class="person-name">${escapeHtml(p.name)}</span>
        <span class="person-meta">${escapeHtml(p.email)}</span>
        <span class="person-status status-${escapeAttr(p.status)}">${escapeHtml(p.status)}</span>
      </button>
    </li>`
      )
      .join("");
  }

  function fillEditor(p) {
    selectedEmail = p.email;
    editorEmpty.classList.add("hidden");
    draftForm.classList.remove("hidden");
    fieldTo.value = p.email || "";
    fieldSubject.value = p.subject || "";
    fieldBody.value = p.body || "";
    fieldNotes.value = p.notes || "";
    draftStatus.textContent = p.status;
    renderSubjects(p.subject_options || [], p.subject || "");
    showMsg(p.error || "", p.error ? "error" : "");
  }

  async function loadPeople() {
    if (!selectedCompany) return;
    const status = statusFilter.value;
    const qs = new URLSearchParams({ company: selectedCompany, limit: "200" });
    if (status && status !== "all") qs.set("status", status);
    const rows = await api(`/api/outreach/contacts?${qs}`);
    peopleTitle.textContent = selectedCompany;
    btnGenBatch.disabled = false;
    renderPeople(rows);
  }

  async function refreshCompanies() {
    const rows = await api("/api/outreach/companies");
    const q = (companyFilter.value || "").toLowerCase();
    const filtered = q ? rows.filter((c) => c.company.toLowerCase().includes(q)) : rows;
    renderCompanies(filtered);
    document.getElementById("stat-companies").textContent = String(rows.length);
    document.getElementById("stat-contacts").textContent = String(
      rows.reduce((n, c) => n + c.total, 0)
    );
  }

  companyList.addEventListener("click", async (e) => {
    const btn = e.target.closest(".company-btn");
    if (!btn) return;
    selectedCompany = btn.dataset.company;
    selectedEmail = "";
    draftForm.classList.add("hidden");
    editorEmpty.classList.remove("hidden");
    [...companyList.querySelectorAll(".company-btn")].forEach((b) =>
      b.classList.toggle("active", b === btn)
    );
    try {
      await loadPeople();
    } catch (err) {
      showMsg(err.message, "error");
    }
  });

  peopleList.addEventListener("click", async (e) => {
    const btn = e.target.closest(".person-btn");
    if (!btn) return;
    try {
      const p = await api(`/api/outreach/contacts/${encodeURIComponent(btn.dataset.email)}`);
      [...peopleList.querySelectorAll(".person-btn")].forEach((b) =>
        b.classList.toggle("active", b === btn)
      );
      fillEditor(p);
    } catch (err) {
      showMsg(err.message, "error");
    }
  });

  companyFilter.addEventListener("input", () => refreshCompanies().catch(() => {}));
  statusFilter.addEventListener("change", () => loadPeople().catch((e) => showMsg(e.message, "error")));

  btnSync.addEventListener("click", async () => {
    btnSync.disabled = true;
    try {
      const r = await api("/api/outreach/sync", { method: "POST" });
      await refreshCompanies();
      showMsg(`Imported ${r.total} contacts across ${r.companies} companies.`, "ok");
    } catch (err) {
      showMsg(err.message, "error");
    } finally {
      btnSync.disabled = false;
    }
  });

  btnGenBatch.addEventListener("click", async () => {
    if (!selectedCompany) return;
    btnGenBatch.disabled = true;
    showMsg("Generating drafts…");
    try {
      const r = await api("/api/outreach/generate-company", {
        method: "POST",
        body: JSON.stringify({
          company: selectedCompany,
          limit: 5,
          notes: fieldNotes.value || "",
          only_pending: true,
        }),
      });
      await loadPeople();
      await refreshCompanies();
      showMsg(`Generated ${r.generated} draft(s).${r.errors?.length ? ` ${r.errors.length} failed.` : ""}`, "ok");
    } catch (err) {
      showMsg(err.message, "error");
    } finally {
      btnGenBatch.disabled = false;
    }
  });

  async function mutate(path, method = "POST", body) {
    if (!selectedEmail) return;
    const opts = { method };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const p = await api(path, opts);
    fillEditor(p);
    await loadPeople();
    await refreshCompanies();
    return p;
  }

  document.getElementById("btn-generate").addEventListener("click", async () => {
    showMsg("Generating…");
    try {
      await mutate(`/api/outreach/contacts/${encodeURIComponent(selectedEmail)}/generate`, "POST", {
        notes: fieldNotes.value || "",
      });
      showMsg("Draft ready — review before sending.", "ok");
    } catch (err) {
      showMsg(err.message, "error");
    }
  });

  function draftPayload() {
    return {
      email: (fieldTo.value || "").trim(),
      subject: fieldSubject.value,
      body: fieldBody.value,
      notes: fieldNotes.value,
    };
  }

  document.getElementById("btn-save").addEventListener("click", async () => {
    try {
      await mutate(`/api/outreach/contacts/${encodeURIComponent(selectedEmail)}/draft`, "PUT", draftPayload());
      showMsg("Saved.", "ok");
    } catch (err) {
      showMsg(err.message, "error");
    }
  });

  document.getElementById("btn-accept").addEventListener("click", async () => {
    try {
      await mutate(`/api/outreach/contacts/${encodeURIComponent(selectedEmail)}/draft`, "PUT", draftPayload());
      await mutate(`/api/outreach/contacts/${encodeURIComponent(selectedEmail)}/accept`);
      showMsg("Accepted. You can send now.", "ok");
    } catch (err) {
      showMsg(err.message, "error");
    }
  });

  document.getElementById("btn-reject").addEventListener("click", async () => {
    try {
      await mutate(`/api/outreach/contacts/${encodeURIComponent(selectedEmail)}/reject`);
      showMsg("Rejected — generate again or edit.", "ok");
    } catch (err) {
      showMsg(err.message, "error");
    }
  });

  document.getElementById("btn-send").addEventListener("click", async () => {
    const to = (fieldTo.value || selectedEmail || "").trim();
    if (!confirm(`Send this email to ${to}?`)) return;
    showMsg("Sending…");
    try {
      await mutate(`/api/outreach/contacts/${encodeURIComponent(selectedEmail)}/draft`, "PUT", draftPayload());
      await mutate(`/api/outreach/contacts/${encodeURIComponent(selectedEmail)}/send`);
      showMsg("Sent.", "ok");
    } catch (err) {
      showMsg(err.message, "error");
    }
  });

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function escapeAttr(s) {
    return escapeHtml(s).replace(/'/g, "&#39;");
  }

  // initial
  if (!companyList.children.length) {
    btnSync.click();
  }
})();
