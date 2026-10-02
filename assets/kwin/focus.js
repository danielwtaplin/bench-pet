// Loaded into KWin by bench-pet: reports the active window back over D-Bus.
function report(w) {
    if (!w) return;
    callDBus("org.benchpet.Pet", "/Focus", "org.benchpet.Focus", "Activated",
             w.pid, String(w.resourceClass), String(w.caption));
}
workspace.windowActivated.connect(report);
report(workspace.activeWindow);
