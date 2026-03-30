// Global variables
let currentStep = 1;
const totalSteps = 5;

// Initialize the page
document.addEventListener('DOMContentLoaded', function() {
    showStep(1);
    updateProgressBar();
});

// Show specific step
function showStep(stepNumber) {
    // Hide all steps
    const steps = document.querySelectorAll('.step');
    steps.forEach(step => {
        step.style.display = 'none';
        step.classList.remove('active');
    });

    // Show selected step
    const selectedStep = document.getElementById(`step${stepNumber}`);
    if (selectedStep) {
        selectedStep.style.display = 'block';
        selectedStep.classList.add('active');
    }

    // Update current step
    currentStep = stepNumber;
    updateProgressBar();
    updateNavigationButtons();
    
    // Scroll to top
    window.scrollTo(0, 0);
}

// Next step
function nextStep() {
    if (currentStep < totalSteps) {
        showStep(currentStep + 1);
    }
}

// Previous step
function previousStep() {
    if (currentStep > 1) {
        showStep(currentStep - 1);
    }
}

// Update progress bar
function updateProgressBar() {
    const percentage = (currentStep / totalSteps) * 100;
    const progressBar = document.getElementById('progressBar');
    const currentStepSpan = document.getElementById('currentStep');
    
    if (progressBar) {
        progressBar.style.width = percentage + '%';
    }
    if (currentStepSpan) {
        currentStepSpan.textContent = currentStep;
    }
}

// Update navigation buttons
function updateNavigationButtons() {
    const prevBtn = document.querySelector('.step-navigation .btn-secondary');
    const nextBtn = document.querySelector('.step-navigation .btn-primary');
    
    if (currentStep === 1) {
        if (prevBtn) prevBtn.style.visibility = 'hidden';
    } else {
        if (prevBtn) prevBtn.style.visibility = 'visible';
    }
    
    if (currentStep === totalSteps) {
        if (nextBtn) nextBtn.textContent = '✓ Complete Setup';
    } else {
        if (nextBtn) nextBtn.textContent = 'Next →';
    }
}

// Copy code to clipboard
function copyCode(button) {
    const codeBlock = button.parentElement;
    const code = codeBlock.querySelector('code').innerText;
    
    navigator.clipboard.writeText(code).then(() => {
        const originalText = button.textContent;
        button.textContent = '✓ Copied!';
        
        setTimeout(() => {
            button.textContent = originalText;
        }, 2000);
    }).catch(err => {
        alert('Failed to copy code');
    });
}

// Update progress (for checkboxes)
function updateProgress() {
    // This function is called when checkboxes are checked
    // You can add logic here to track completion
}

// Complete setup
function completeSetup() {
    const modal = document.getElementById('completionModal');
    if (modal) {
        modal.classList.add('active');
    }
}

// Close modal
function closeModal() {
    const modal = document.getElementById('completionModal');
    if (modal) {
        modal.classList.remove('active');
    }
}

// Scroll to step
function scrollToStep(stepNumber) {
    showStep(stepNumber);
}

// Smooth scroll behavior
document.addEventListener('click', function(e) {
    if (e.target.tagName === 'A' && e.target.getAttribute('href') === '#') {
        e.preventDefault();
    }
});

// Add keyboard navigation
document.addEventListener('keydown', function(e) {
    if (e.key === 'ArrowRight') {
        nextStep();
    } else if (e.key === 'ArrowLeft') {
        previousStep();
    }
});

// Add smooth animations
const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.style.opacity = '1';
            entry.target.style.transform = 'translateY(0)';
        }
    });
}, {
    threshold: 0.1
});

// Observe all setup sections
document.querySelectorAll('.setup-section').forEach(section => {
    section.style.opacity = '0';
    section.style.transform = 'translateY(10px)';
    section.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
    observer.observe(section);
});
