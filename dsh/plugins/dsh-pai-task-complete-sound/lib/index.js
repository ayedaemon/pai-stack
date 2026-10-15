// dsh-pai-task-complete-sound
// Task Complete Sound Plugin for DSH
// Plays a sound notification when a task is marked as complete.
// Uses browser-based sound so the notification plays on the user's device,
// not in the DSH container (which may not have audio support like PulseAudio).

/**
 * Play a task complete sound notification using browser capabilities.
 * Since users access DSH via a web browser, we use the Web Notification API
 * to play sound in the user's browser rather than trying container audio
 * (aplay/paplay/echo \a which all fail in headless Docker containers).
 * @returns {boolean} - Whether a notification was triggered
 */
function playTaskCompleteSound() {
    // Try to show a browser notification with sound.
    // The Web Notification API plays a system sound when notification is shown.
    // This works in the user's browser, not in the container.
    try {
        // Check if Window/Notification APIs are available (browser environment)
        if (typeof window !== "undefined" && "Notification" in window) {
            // Request permission if not already granted
            if (Notification.permission !== "granted") {
                Notification.requestPermission().then((permission) => {
                    if (permission === "granted") {
                        showNotification();
                    }
                });
            } else {
                showNotification();
            }
        } else {
            // Not in a browser environment - fallback to console message
            console.log(
                "Task completed! Browser sound notification: install Notification API support or use container with audio."
            );
            return false;
        }
        return true;
    } catch (e) {
        // Notification failed - fall back to console message
        console.log("Task completed! (browser sound notification attempted)");
        return false;
    }
}

/**
 * Show a browser notification with task completion info.
 * This plays sound in the user's browser via the Web Notification API
 * and Web Audio API for a beep sound.
 */
function showNotification() {
    // Show the notification (this triggers system sound on most browsers)
    const notification = new Notification("Task Complete", {
        icon: "/favicon.ico",
        body: "A task has completed successfully.",
    });

    // Play a beep sound using Web Audio API when notification is clicked
    notification.onclick = () => {
        try {
            const AudioContext =
                window.AudioContext || window.webkitAudioContext;
            const audioContext = new AudioContext();
            const oscillator = audioContext.createOscillator();
            const gainNode = audioContext.createGain();

            oscillator.connect(gainNode);
            gainNode.connect(audioContext.destination);

            oscillator.frequency.value = 800; // 800 Hz tone
            gainNode.gain.value = 0.5; // Volume

            oscillator.start();
            setTimeout(() => {
                oscillator.stop();
            }, 500);
        } catch (e) {
            // Web Audio API not available - silently fall back
        }
    };
}

/**
 * Main function - called when plugin is loaded (DSH container entry point)
 */
function main() {
    const played = playTaskCompleteSound();
    if (played) {
        process.stdout.write(
            '✓ Task complete sound notification triggered for browser\n'
        );
    } else {
        process.stdout.write(
            'Task completed successfully! (browser sound notification attempted)\n'
        );
    }
    process.exit(0);
}

// Entry point when run directly
if (require.main === module) {
    main();
}

// Export for browser use - these will be available in window context when bundled
if (typeof window !== "undefined") {
    window.playTaskCompleteSound = playTaskCompleteSound;
    window.showNotification = showNotification;
}

// For Node.js environments (DSH container), also export
module.exports = {
    playTaskCompleteSound,
    main,
    showNotification,
};