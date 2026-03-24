document.addEventListener("DOMContentLoaded", function () {
    // -----------------------------
    // Auto-dismiss flash messages
    // -----------------------------
    document.querySelectorAll('[data-auto-dismiss="true"]').forEach(function (alertEl) {
        window.setTimeout(function () {
            if (!alertEl.classList.contains("show")) return;
            const alertInstance = bootstrap.Alert.getOrCreateInstance(alertEl);
            alertInstance.close();
        }, 5000);
    });

    // -----------------------------
    // Helper: activate nav links by current path when template checks are incomplete
    // -----------------------------
    const currentPath = window.location.pathname;
    document.querySelectorAll(".app-primary-nav .nav-link, .admin-nav-link").forEach(function (link) {
        const href = link.getAttribute("href");
        if (!href || href === "#") return;
        try {
            const url = new URL(href, window.location.origin);
            if (!link.classList.contains("active") && url.pathname !== "/" && currentPath.startsWith(url.pathname)) {
                link.classList.add("active");
            }
        } catch (error) {
            // Ignore invalid hrefs
        }
    });

    // -----------------------------
    // Category -> custom_category toggle
    // -----------------------------
    const categoryField = document.getElementById("category");
    const customCategoryField = document.getElementById("custom_category");

    function toggleCustomCategory() {
        if (!categoryField || !customCategoryField) return;

        if (categoryField.value === "Other") {
            customCategoryField.disabled = false;
            customCategoryField.placeholder = "Please specify";
        } else {
            customCategoryField.value = "";
            customCategoryField.disabled = true;
            customCategoryField.placeholder = "Only enabled when 'Other' is selected";
        }
    }

    if (categoryField && customCategoryField) {
        toggleCustomCategory();
        categoryField.addEventListener("change", toggleCustomCategory);
    }

    // -----------------------------
    // Resume choice toggle
    // -----------------------------
    const resumeChoice = document.getElementById("resume_choice");
    const customResumeWrapper = document.getElementById("custom-resume-wrapper");
    const uploadCvInsteadBtn = document.getElementById("upload-cv-instead-btn");

    function toggleCustomResume() {
        if (!resumeChoice || !customResumeWrapper) return;

        if (resumeChoice.value === "custom") {
            customResumeWrapper.style.display = "block";
        } else {
            customResumeWrapper.style.display = "none";
            const fileInput = customResumeWrapper.querySelector('input[type="file"]');
            if (fileInput) {
                fileInput.value = "";
            }
        }
    }

    if (resumeChoice && customResumeWrapper) {
        toggleCustomResume();
        resumeChoice.addEventListener("change", toggleCustomResume);
    }

    if (uploadCvInsteadBtn && resumeChoice) {
        uploadCvInsteadBtn.addEventListener("click", function () {
            resumeChoice.value = "custom";
            toggleCustomResume();

            const fileInput = document.querySelector('#custom-resume-wrapper input[type="file"]');
            if (fileInput) {
                fileInput.scrollIntoView({ behavior: "smooth", block: "center" });
                fileInput.focus();
            }
        });
    }

    // -----------------------------
    // Schedule type UI
    // -----------------------------
    const scheduleType = document.getElementById("schedule_type");
    const oneTimeFields = document.getElementById("one-time-fields");
    const dateRangeFields = document.getElementById("date-range-fields");
    const weeklyFields = document.getElementById("weekly-fields");
    const monthlyFields = document.getElementById("monthly-fields");

    const dateNeeded = document.getElementById("date_needed");
    const startDate = document.getElementById("start_date");
    const endDate = document.getElementById("end_date");
    const startTime = document.getElementById("start_time");
    const endTime = document.getElementById("end_time");

    const today = new Date().toISOString().split("T")[0];

    function toggleScheduleFields() {
        if (!scheduleType) return;

        const value = scheduleType.value;

        if (oneTimeFields) {
            oneTimeFields.style.display = value === "one_time" ? "block" : "none";
        }
        if (dateRangeFields) {
            dateRangeFields.style.display = ["date_range", "recurring_weekly", "recurring_monthly"].includes(value) ? "block" : "none";
        }
        if (weeklyFields) {
            weeklyFields.style.display = value === "recurring_weekly" ? "block" : "none";
        }
        if (monthlyFields) {
            monthlyFields.style.display = value === "recurring_monthly" ? "block" : "none";
        }
    }

    function applyDateMinimums() {
        if (dateNeeded) dateNeeded.min = today;
        if (startDate) startDate.min = today;
        if (endDate) endDate.min = today;
    }

    function syncDateConstraints() {
        if (!startDate || !endDate) return;

        if (startDate.value) {
            endDate.min = startDate.value;
        } else {
            endDate.min = today;
        }

        if (endDate.value && startDate.value && endDate.value < startDate.value) {
            endDate.value = "";
        }
    }

    function syncTimeConstraints() {
        if (!startTime || !endTime) return;

        endTime.min = startTime.value || "";

        if (startTime.value && endTime.value && endTime.value <= startTime.value) {
            endTime.value = "";
        }
    }

    if (scheduleType) {
        applyDateMinimums();
        toggleScheduleFields();
        scheduleType.addEventListener("change", toggleScheduleFields);
    }

    if (startDate) startDate.addEventListener("change", syncDateConstraints);
    if (endDate) endDate.addEventListener("change", syncDateConstraints);
    if (startTime) startTime.addEventListener("change", syncTimeConstraints);
    if (endTime) endTime.addEventListener("change", syncTimeConstraints);

    syncDateConstraints();
    syncTimeConstraints();

    // -----------------------------
    // Generic collapsible toolbar support
    // -----------------------------
    document.querySelectorAll("[data-toggle-target]").forEach(function (toggleBtn) {
        toggleBtn.addEventListener("click", function () {
            const selector = toggleBtn.getAttribute("data-toggle-target");
            if (!selector) return;
            const target = document.querySelector(selector);
            if (!target) return;

            const isHidden = window.getComputedStyle(target).display === "none";
            target.style.display = isHidden ? "block" : "none";
            toggleBtn.setAttribute("aria-expanded", String(isHidden));
        });
    });

    // -----------------------------
    // Browse Requests - live search and instant filters
    // -----------------------------
    const browseFilterForm = document.getElementById("browse-requests-filter-form");
    const browseResults = document.getElementById("browse-requests-results");
    const browseLoading = document.getElementById("browse-live-loading");
    const browseStatus = document.getElementById("browse-live-status");

    if (browseFilterForm && browseResults) {
        const searchInput = document.getElementById("browse-search-input");
        const cityInput = document.getElementById("browse-city-filter");

        const instantFields = [
            document.getElementById("browse-category-filter"),
            document.getElementById("browse-urgency-filter"),
            document.getElementById("browse-experience-filter"),
            document.getElementById("browse-schedule-filter"),
            document.getElementById("browse-sort-filter")
        ].filter(Boolean);

        let debounceTimer = null;
        let activeRequestController = null;

        function setLoadingState(isLoading) {
            if (browseLoading) {
                browseLoading.classList.toggle("d-none", !isLoading);
            }
            if (browseStatus) {
                browseStatus.textContent = isLoading ? "Updating results..." : "Showing matching requests";
            }
        }

        async function refreshBrowseRequests() {
            const formData = new FormData(browseFilterForm);
            const params = new URLSearchParams(formData);
            const url = `${browseFilterForm.action}?${params.toString()}`;

            if (activeRequestController) {
                activeRequestController.abort();
            }

            activeRequestController = new AbortController();
            setLoadingState(true);

            try {
                const response = await fetch(url, {
                    method: "GET",
                    headers: {
                        "X-Requested-With": "XMLHttpRequest"
                    },
                    signal: activeRequestController.signal
                });

                if (!response.ok) {
                    throw new Error("Failed to refresh requests.");
                }

                const html = await response.text();
                browseResults.innerHTML = html;

                const cleanUrl = `${browseFilterForm.action}?${params.toString()}`;
                window.history.replaceState({}, "", cleanUrl);
            } catch (error) {
                if (error.name !== "AbortError") {
                    console.error("Browse requests live filter error:", error);
                }
            } finally {
                setLoadingState(false);
            }
        }

        function debounceRefresh() {
            window.clearTimeout(debounceTimer);
            debounceTimer = window.setTimeout(refreshBrowseRequests, 300);
        }

        if (searchInput) {
            searchInput.addEventListener("input", debounceRefresh);
        }

        if (cityInput) {
            cityInput.addEventListener("input", debounceRefresh);
        }

        instantFields.forEach(function (field) {
            field.addEventListener("change", refreshBrowseRequests);
        });

        browseFilterForm.addEventListener("submit", function (event) {
            event.preventDefault();
            refreshBrowseRequests();
        });
    }

    // -----------------------------
    // Admin verification viewer button polish
    // -----------------------------
    const certificateViewBtn = document.querySelector(".admin-certificate-view-btn");
    if (certificateViewBtn) {
        certificateViewBtn.addEventListener("click", function () {
            const label = certificateViewBtn.getAttribute("data-open-label") || "Opening certificate viewer...";
            certificateViewBtn.classList.add("disabled");
            certificateViewBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>${label}`;
        });
    }
});

// -----------------------------
// Learning Hub UX helpers
// -----------------------------
document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".learning-question-builder").forEach(function (form) {
        const questionType = form.querySelector(".js-question-type");
        const mcqOptions = form.querySelector(".js-mcq-options");
        const booleanPreview = form.querySelector(".js-boolean-preview");
        const correctAnswer = form.querySelector(".js-correct-answer");

        function refreshQuestionMode() {
            if (!questionType || !correctAnswer) return;
            const isTrueFalse = questionType.value === "true_false";

            if (mcqOptions) {
                mcqOptions.classList.toggle("d-none", isTrueFalse);
                mcqOptions.querySelectorAll("input").forEach(function (input) {
                    input.disabled = isTrueFalse;
                });
            }

            if (booleanPreview) {
                booleanPreview.classList.toggle("d-none", !isTrueFalse);
            }

            const options = isTrueFalse
                ? [
                    { value: "A", label: "A · TRUE" },
                    { value: "B", label: "B · FALSE" }
                ]
                : [
                    { value: "A", label: "A" },
                    { value: "B", label: "B" },
                    { value: "C", label: "C" },
                    { value: "D", label: "D" }
                ];

            const currentValue = correctAnswer.value;
            correctAnswer.innerHTML = "";
            options.forEach(function (item, index) {
                const option = document.createElement("option");
                option.value = item.value;
                option.textContent = item.label;
                option.selected = currentValue === item.value || (!currentValue && index === 0);
                correctAnswer.appendChild(option);
            });

            if (isTrueFalse && !["A", "B"].includes(correctAnswer.value)) {
                correctAnswer.value = "A";
            }
        }

        if (questionType) {
            questionType.addEventListener("change", refreshQuestionMode);
            refreshQuestionMode();
        }
    });

    document.querySelectorAll('.learning-tabbar a[href^="#"]').forEach(function (link) {
        link.addEventListener("click", function () {
            document.querySelectorAll(".learning-tabbar-link").forEach(function (item) {
                item.classList.remove("active");
            });
            link.classList.add("active");
        });
    });

    // Intentionally do not auto-logout on unload/refresh/navigation.\n    // Browsers fire unload in many normal navigation cases, which caused random logouts.\n    }
});


document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll('.learning-block-form').forEach(function (form) {
        const typeField = form.querySelector('.js-learning-block-type');
        const fileField = form.querySelector('.js-learning-file-input');
        function syncBlockFields() {
            if (!typeField || !fileField) return;
            const type = typeField.value;
            const disableFile = type === 'text' || type === 'link';
            fileField.disabled = disableFile;
            if (disableFile) fileField.value = '';
        }
        if (typeField) { typeField.addEventListener('change', syncBlockFields); syncBlockFields(); }
    });

    const teacherTabLinks = document.querySelectorAll('.learning-tabbar-link');
    if (teacherTabLinks.length) {
        const storageKey = 'skillsinn_teacher_course_anchor';
        const savedAnchor = window.location.hash || sessionStorage.getItem(storageKey);
        if (savedAnchor) {
            const target = document.querySelector(savedAnchor);
            if (target && !window.location.hash) {
                setTimeout(function(){ target.scrollIntoView({behavior:'smooth', block:'start'}); }, 120);
            }
        }
        teacherTabLinks.forEach(function(link){
            link.addEventListener('click', function(){ sessionStorage.setItem(storageKey, link.getAttribute('href')); });
        });
        document.querySelectorAll('[data-learning-anchor]').forEach(function(el){
            el.addEventListener('submit', function(){ const anchor = el.getAttribute('data-learning-anchor'); if (anchor) sessionStorage.setItem(storageKey, '#' + anchor.replace(/^#/, '')); });
        });
    }

    const learningHubFilterForm = document.getElementById('learning-hub-filter-form');
    const learningHubSearch = document.getElementById('learning-hub-search');
    let learningHubTimer = null;
    function submitLearningHubFilters() { if (learningHubFilterForm) learningHubFilterForm.submit(); }
    document.querySelectorAll('.learning-hub-auto-submit').forEach(function(field){ field.addEventListener('change', submitLearningHubFilters); });
    if (learningHubSearch) {
        learningHubSearch.addEventListener('input', function(){ clearTimeout(learningHubTimer); learningHubTimer = setTimeout(submitLearningHubFilters, 250); });
    }
});
