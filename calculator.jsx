import { useState, useRef, useCallback, useEffect } from "react";

// ─── Fake working generator ───────────────────────────────────────────────────
// Given a target number and the 3 operators the user pressed,
// reverse-engineer 4 plausible-looking numbers that evaluate to target.
// iOS calculator evaluates strictly left-to-right: ((A op1 B) op2 C) op3 D = T
function generateFakeWorking(target, ops, userNums) {
  // We'll try to keep numbers in a similar magnitude to what the user typed
  const magnitude = (n) => Math.max(1, Math.floor(Math.log10(Math.abs(n) + 1)));
  const avgMag = userNums.reduce((s, n) => s + magnitude(n), 0) / userNums.length;
  const randLike = (mag) => Math.floor(Math.random() * 9 * Math.pow(10, mag - 1) + Math.pow(10, mag - 1));

  const applyOp = (a, op, b) => {
    if (op === "×") return a * b;
    if (op === "÷") return b !== 0 ? a / b : a;
    if (op === "+") return a + b;
    if (op === "−") return a - b;
    return a;
  };

  // Try up to 200 times to find integers that work
  for (let attempt = 0; attempt < 200; attempt++) {
    const mag = Math.max(1, Math.round(avgMag + (Math.random() - 0.5)));
    const A = randLike(mag);
    const B = randLike(mag);
    const C = randLike(mag);

    // After A op1 B op2 C, we need the result op3 D = target
    const partial = applyOp(applyOp(A, ops[0], B), ops[1], C);

    let D;
    if (ops[2] === "+") D = target - partial;
    else if (ops[2] === "−") D = partial - target;
    else if (ops[2] === "×") {
      if (partial === 0) continue;
      D = target / partial;
    } else if (ops[2] === "÷") {
      D = partial / target;
      if (D === 0 || !isFinite(D)) continue;
    }

    if (D === undefined || !isFinite(D) || isNaN(D)) continue;
    // Keep D as a clean-ish integer
    D = Math.round(D);
    if (D <= 0) continue;

    // Verify
    const result = applyOp(applyOp(applyOp(A, ops[0], B), ops[1], C), ops[2], D);
    if (Math.abs(result - target) < 0.01) {
      return [A, B, C, D];
    }
  }

  // Fallback: just use user's original numbers — the display won't perfectly match but won't crash
  return userNums.slice(0, 4);
}

function formatNum(n) {
  if (n === null || n === undefined) return "0";
  const s = String(n);
  // Already formatted string (e.g. mid-entry)
  if (s === "0" || s === "-" || s.endsWith(".")) return s;
  const num = parseFloat(n);
  if (isNaN(num)) return "0";
  // Large numbers use locale formatting
  if (Math.abs(num) >= 1e9) return num.toLocaleString("en-US", { maximumFractionDigits: 2 });
  // Show up to 9 significant digits
  const formatted = parseFloat(num.toPrecision(9));
  return formatted.toLocaleString("en-US", { maximumFractionDigits: 8 });
}

export default function IOSCalculator() {
  // ── Calculator state ──────────────────────────────────────────────────────
  const [display, setDisplay] = useState("0");
  const [expression, setExpression] = useState("");
  const [storedValue, setStoredValue] = useState(null);
  const [pendingOp, setPendingOp] = useState(null);
  const [waitingForOperand, setWaitingForOperand] = useState(false);
  const [justEvaluated, setJustEvaluated] = useState(false);

  // Rigged mode tracking
  const [targetNumber, setTargetNumber] = useState(null);
  const [inputCount, setInputCount] = useState(0); // how many numbers entered
  const [operatorSequence, setOperatorSequence] = useState([]);
  const [numberSequence, setNumberSequence] = useState([]);
  const [riggedMode, setRiggedMode] = useState(false); // currently in a rigged sequence

  // Secret menu
  const [showSecret, setShowSecret] = useState(false);
  const [secretInput, setSecretInput] = useState("");
  const [secretSaved, setSecretSaved] = useState(false);
  const longPressTimer = useRef(null);
  const longPressStart = useRef(null);

  // ── Display sizing ────────────────────────────────────────────────────────
  const displayFontSize = display.replace(/[^0-9.]/g, "").length > 9 ? "2.8rem"
    : display.length > 7 ? "3.8rem" : "5rem";

  // ── Core calc logic ───────────────────────────────────────────────────────
  const calculate = (a, op, b) => {
    const numA = parseFloat(a);
    const numB = parseFloat(b);
    if (op === "+") return numA + numB;
    if (op === "−") return numA - numB;
    if (op === "×") return numA * numB;
    if (op === "÷") return numB !== 0 ? numA / numB : "Error";
    return numB;
  };

  const handleDigit = (digit) => {
    if (showSecret) return;
    setJustEvaluated(false);

    if (waitingForOperand || justEvaluated) {
      setDisplay(digit === "." ? "0." : digit);
      setWaitingForOperand(false);
    } else {
      if (digit === "." && display.includes(".")) return;
      if (display === "0" && digit !== ".") {
        setDisplay(digit);
      } else {
        if (display.replace(".", "").replace("-", "").length >= 9) return;
        setDisplay(display + digit);
      }
    }
  };

  const handleOperator = (op) => {
    if (showSecret) return;
    const current = parseFloat(display);

    // Track number sequence for rigged mode
    if (targetNumber !== null) {
      if (!riggedMode) {
        setRiggedMode(true);
        setNumberSequence([current]);
        setOperatorSequence([op]);
        setInputCount(1);
      } else {
        const newNums = [...numberSequence, current];
        const newOps = [...operatorSequence, op];
        setNumberSequence(newNums);
        setOperatorSequence(newOps);
        setInputCount(inputCount + 1);
      }
    }

    if (storedValue !== null && !waitingForOperand) {
      const result = calculate(storedValue, pendingOp, display);
      setDisplay(String(result));
      setStoredValue(result);
      setExpression(`${formatNum(result)} ${op}`);
    } else {
      setStoredValue(current);
      setExpression(`${formatNum(current)} ${op}`);
    }
    setPendingOp(op);
    setWaitingForOperand(true);
  };

  const handleEquals = () => {
    if (showSecret) return;
    if (storedValue === null || pendingOp === null) return;

    const current = parseFloat(display);

    // ── Rigged equals ──────────────────────────────────────────────────────
    if (targetNumber !== null && riggedMode) {
      const allNums = [...numberSequence, current];
      const allOps = operatorSequence;

      // Only rig if we have 4 numbers and 3 operators
      if (allNums.length >= 4 && allOps.length >= 3) {
        const fakeNums = generateFakeWorking(targetNumber, allOps.slice(0, 3), allNums);
        const fakeExpr = `${fakeNums[0].toLocaleString("en-US")}${allOps[0]}${fakeNums[1].toLocaleString("en-US")}÷${fakeNums[2].toLocaleString("en-US")}${allOps[2]}${fakeNums[3].toLocaleString("en-US")}`;
        setExpression(fakeExpr);
        setDisplay(formatNum(targetNumber));
        setStoredValue(null);
        setPendingOp(null);
        setWaitingForOperand(false);
        setJustEvaluated(true);
        setRiggedMode(false);
        setNumberSequence([]);
        setOperatorSequence([]);
        setInputCount(0);
        return;
      }
    }

    // ── Normal equals ──────────────────────────────────────────────────────
    const result = calculate(storedValue, pendingOp, display);
    const expr = `${formatNum(storedValue)} ${pendingOp} ${formatNum(current)}`;
    setExpression(expr);
    setDisplay(String(result));
    setStoredValue(null);
    setPendingOp(null);
    setWaitingForOperand(false);
    setJustEvaluated(true);
    setRiggedMode(false);
    setNumberSequence([]);
    setOperatorSequence([]);
    setInputCount(0);
  };

  const handleAC = () => {
    if (showSecret) return;
    setDisplay("0");
    setExpression("");
    setStoredValue(null);
    setPendingOp(null);
    setWaitingForOperand(false);
    setJustEvaluated(false);
    setRiggedMode(false);
    setNumberSequence([]);
    setOperatorSequence([]);
    setInputCount(0);
  };

  const handleBackspace = () => {
    if (showSecret) return;
    if (display.length <= 1) { setDisplay("0"); return; }
    setDisplay(display.slice(0, -1));
  };

  const handlePercent = () => {
    if (showSecret) return;
    const val = parseFloat(display) / 100;
    setDisplay(String(val));
  };

  const handlePlusMinus = () => {
    if (showSecret) return;
    if (display === "0") return;
    setDisplay(display.startsWith("-") ? display.slice(1) : "-" + display);
  };

  // ── Long press % for secret menu ──────────────────────────────────────────
  const startLongPress = () => {
    longPressStart.current = Date.now();
    longPressTimer.current = setTimeout(() => {
      setShowSecret(true);
      setSecretSaved(false);
      if (targetNumber !== null) setSecretInput(String(targetNumber));
    }, 5000);
  };

  const cancelLongPress = () => {
    if (longPressTimer.current) clearTimeout(longPressTimer.current);
    // If not long enough, treat as normal percent press
    if (longPressStart.current && Date.now() - longPressStart.current < 5000) {
      handlePercent();
    }
    longPressStart.current = null;
  };

  const confirmSecret = () => {
    const val = parseFloat(secretInput);
    if (!isNaN(val)) {
      setTargetNumber(val);
      setSecretSaved(true);
      setTimeout(() => setShowSecret(false), 800);
    }
  };

  const clearTarget = () => {
    setTargetNumber(null);
    setSecretInput("");
    setSecretSaved(false);
    setShowSecret(false);
  };

  // ── Keyboard support ──────────────────────────────────────────────────────
  useEffect(() => {
    const onKey = (e) => {
      if (showSecret) return;
      if ("0123456789".includes(e.key)) handleDigit(e.key);
      else if (e.key === ".") handleDigit(".");
      else if (e.key === "+") handleOperator("+");
      else if (e.key === "-") handleOperator("−");
      else if (e.key === "*") handleOperator("×");
      else if (e.key === "/") { e.preventDefault(); handleOperator("÷"); }
      else if (e.key === "Enter" || e.key === "=") handleEquals();
      else if (e.key === "Backspace") handleBackspace();
      else if (e.key === "Escape") handleAC();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // ── Button press animation ────────────────────────────────────────────────
  const [pressed, setPressed] = useState(null);
  const press = (id, fn) => {
    setPressed(id);
    setTimeout(() => setPressed(null), 120);
    fn();
  };

  // ── Render ────────────────────────────────────────────────────────────────
  const Btn = ({ id, label, type = "num", onPress, onPressStart, onPressEnd, wide = false }) => {
    const base = {
      num: { bg: "#333333", fg: "#ffffff" },
      op: { bg: "#FF9F0A", fg: "#ffffff" },
      fn: { bg: "#A5A5A5", fg: "#000000" },
      opActive: { bg: "#ffffff", fg: "#FF9F0A" },
    };
    const isActiveOp = pendingOp === label && waitingForOperand;
    const scheme = isActiveOp ? base.opActive : base[type];
    const isPressed = pressed === id;

    return (
      <button
        onPointerDown={(e) => { e.preventDefault(); onPressStart?.(); if (!onPressStart) press(id, onPress); }}
        onPointerUp={(e) => { e.preventDefault(); onPressEnd?.(); }}
        onPointerLeave={(e) => { onPressEnd?.(); }}
        style={{
          width: wide ? "calc(50% - 6px)" : "calc(25% - 9px)",
          aspectRatio: wide ? "2.1/1" : "1/1",
          borderRadius: "50px",
          background: isPressed ? (type === "op" ? "#ffc966" : type === "fn" ? "#d4d4d4" : "#636363") : scheme.bg,
          color: scheme.fg,
          fontSize: label === "AC" || label === "⌫" ? "1.4rem" : "1.9rem",
          fontWeight: "400",
          border: "none",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          paddingLeft: wide ? "1.4rem" : 0,
          userSelect: "none",
          WebkitUserSelect: "none",
          transition: "background 0.07s",
          fontFamily: "-apple-system, 'SF Pro Display', 'Helvetica Neue', sans-serif",
          letterSpacing: "-0.02em",
          flexShrink: 0,
        }}
      >
        {label}
      </button>
    );
  };

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      minHeight: "100vh",
      background: "#000",
      fontFamily: "-apple-system, 'SF Pro Display', 'Helvetica Neue', sans-serif",
    }}>
      {/* Calculator shell */}
      <div style={{
        width: "min(390px, 100vw)",
        minHeight: "min(844px, 100vh)",
        background: "#000",
        display: "flex",
        flexDirection: "column",
        justifyContent: "flex-end",
        padding: "0 12px 20px 12px",
        boxSizing: "border-box",
        position: "relative",
      }}>

        {/* ── Display ── */}
        <div style={{
          padding: "0 8px",
          marginBottom: "8px",
          minHeight: "160px",
          display: "flex",
          flexDirection: "column",
          justifyContent: "flex-end",
          alignItems: "flex-end",
        }}>
          {/* Expression / working */}
          <div style={{
            color: "#8a8a8a",
            fontSize: "1.2rem",
            letterSpacing: "0.01em",
            marginBottom: "2px",
            minHeight: "1.5rem",
            wordBreak: "break-all",
            textAlign: "right",
          }}>
            {expression}
          </div>
          {/* Main result */}
          <div style={{
            color: "#fff",
            fontSize: displayFontSize,
            fontWeight: "200",
            letterSpacing: "-0.02em",
            lineHeight: 1,
            textAlign: "right",
            transition: "font-size 0.1s",
          }}>
            {display}
          </div>
        </div>

        {/* ── Button grid ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>

          {/* Row 1 */}
          <div style={{ display: "flex", gap: "10px" }}>
            <Btn id="ac" label="AC" type="fn" onPress={handleAC} />
            <Btn id="pm" label="+/−" type="fn" onPress={handlePlusMinus} />
            <Btn
              id="pct"
              label="%"
              type="fn"
              onPress={() => { }}
              onPressStart={startLongPress}
              onPressEnd={cancelLongPress}
            />
            <Btn id="div" label="÷" type="op" onPress={() => press("div", () => handleOperator("÷"))} />
          </div>

          {/* Row 2 */}
          <div style={{ display: "flex", gap: "10px" }}>
            <Btn id="7" label="7" onPress={() => handleDigit("7")} />
            <Btn id="8" label="8" onPress={() => handleDigit("8")} />
            <Btn id="9" label="9" onPress={() => handleDigit("9")} />
            <Btn id="mul" label="×" type="op" onPress={() => handleOperator("×")} />
          </div>

          {/* Row 3 */}
          <div style={{ display: "flex", gap: "10px" }}>
            <Btn id="4" label="4" onPress={() => handleDigit("4")} />
            <Btn id="5" label="5" onPress={() => handleDigit("5")} />
            <Btn id="6" label="6" onPress={() => handleDigit("6")} />
            <Btn id="sub" label="−" type="op" onPress={() => handleOperator("−")} />
          </div>

          {/* Row 4 */}
          <div style={{ display: "flex", gap: "10px" }}>
            <Btn id="1" label="1" onPress={() => handleDigit("1")} />
            <Btn id="2" label="2" onPress={() => handleDigit("2")} />
            <Btn id="3" label="3" onPress={() => handleDigit("3")} />
            <Btn id="add" label="+" type="op" onPress={() => handleOperator("+")} />
          </div>

          {/* Row 5 */}
          <div style={{ display: "flex", gap: "10px" }}>
            <Btn id="0" label="0" wide onPress={() => handleDigit("0")} />
            <Btn id="dot" label="." onPress={() => handleDigit(".")} />
            <Btn id="eq" label="=" type="op" onPress={handleEquals} />
          </div>
        </div>

        {/* ── Target indicator dot ── */}
        {targetNumber !== null && (
          <div style={{
            position: "absolute",
            top: "18px",
            right: "20px",
            width: "8px",
            height: "8px",
            borderRadius: "50%",
            background: "#FF9F0A",
            opacity: 0.7,
          }} />
        )}

        {/* ── Secret menu overlay ── */}
        {showSecret && (
          <div style={{
            position: "absolute",
            inset: 0,
            background: "rgba(0,0,0,0.92)",
            backdropFilter: "blur(20px)",
            WebkitBackdropFilter: "blur(20px)",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: "20px",
            zIndex: 100,
            borderRadius: "0",
            padding: "40px 28px",
            boxSizing: "border-box",
          }}>
            {/* Close */}
            <button
              onClick={() => setShowSecret(false)}
              style={{
                position: "absolute",
                top: "20px",
                right: "20px",
                background: "none",
                border: "none",
                color: "#888",
                fontSize: "1.8rem",
                cursor: "pointer",
                lineHeight: 1,
              }}
            >×</button>

            {/* Lock icon */}
            <div style={{ fontSize: "2.5rem", opacity: 0.4 }}>🔒</div>

            <div style={{
              color: "#fff",
              fontSize: "1.1rem",
              fontWeight: "600",
              letterSpacing: "0.05em",
              textTransform: "uppercase",
              opacity: 0.8,
            }}>
              Configuration
            </div>

            <div style={{
              color: "#888",
              fontSize: "0.8rem",
              letterSpacing: "0.04em",
              textTransform: "uppercase",
              marginTop: "-10px",
            }}>
              Target Number
            </div>

            <input
              type="number"
              value={secretInput}
              onChange={(e) => setSecretInput(e.target.value)}
              placeholder="Enter target…"
              autoFocus
              style={{
                width: "100%",
                padding: "16px 20px",
                background: "#1c1c1e",
                border: "1px solid #3a3a3c",
                borderRadius: "12px",
                color: "#fff",
                fontSize: "1.6rem",
                textAlign: "center",
                outline: "none",
                letterSpacing: "0.02em",
                fontFamily: "-apple-system, 'SF Pro Display', sans-serif",
              }}
            />

            <button
              onClick={confirmSecret}
              style={{
                width: "100%",
                padding: "16px",
                background: secretSaved ? "#30d158" : "#FF9F0A",
                border: "none",
                borderRadius: "12px",
                color: "#fff",
                fontSize: "1.1rem",
                fontWeight: "600",
                cursor: "pointer",
                letterSpacing: "0.02em",
                transition: "background 0.3s",
              }}
            >
              {secretSaved ? "✓ Saved" : "Set Target"}
            </button>

            {targetNumber !== null && (
              <button
                onClick={clearTarget}
                style={{
                  background: "none",
                  border: "none",
                  color: "#ff453a",
                  fontSize: "0.95rem",
                  cursor: "pointer",
                  letterSpacing: "0.02em",
                }}
              >
                Clear Target
              </button>
            )}

            {targetNumber !== null && (
              <div style={{ color: "#555", fontSize: "0.8rem" }}>
                Current: {targetNumber.toLocaleString("en-US")}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
