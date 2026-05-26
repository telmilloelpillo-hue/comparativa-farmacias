/**
 * barcode_scanner.js — Wrapper sobre @zxing/browser para escaneo de códigos de barras 1D.
 *
 * Requiere en el HTML (antes de este script):
 *   <script src="https://unpkg.com/@zxing/browser@0.1.1/umd/index.min.js"></script>
 *
 * API pública:
 *   BarcodeScanner.startCamera(videoEl, onDetected)  → Promise<void>
 *     Inicia cámara, llama onDetected(texto) al leer un código, para la cámara automáticamente.
 *   BarcodeScanner.stopCamera()
 *     Para el stream de cámara si está activo.
 *   BarcodeScanner.decodeFromFile(file)              → Promise<string>
 *     Decodifica el primer código de barras de un File. Lanza Error si no hay código.
 */

const BarcodeScanner = (() => {
    const codeReader = new ZXingBrowser.BrowserMultiFormatReader();
    let activeControls = null;

    /**
     * Inicia el stream de cámara y llama onDetected(texto) al leer un código.
     * La cámara se para automáticamente tras el primer resultado.
     * @param {HTMLVideoElement} videoEl - elemento <video> donde mostrar el stream
     * @param {function(string): void} onDetected - callback con el texto del código
     * @returns {Promise<void>}
     */
    async function startCamera(videoEl, onDetected) {
        if (activeControls) {
            activeControls.stop();
            activeControls = null;
        }
        try {
            activeControls = await codeReader.decodeFromVideoDevice(
                null,      // null = cámara trasera en móvil, predeterminada en PC
                videoEl,
                (result, err) => {
                    if (result) {
                        activeControls.stop();
                        activeControls = null;
                        _beep();
                        onDetected(result.getText());
                    }
                }
            );
        } catch (err) {
            throw new Error('No se pudo acceder a la cámara: ' + err.message);
        }
    }

    /** Para el stream de cámara si está activo. */
    function stopCamera() {
        if (activeControls) {
            activeControls.stop();
            activeControls = null;
        }
    }

    /**
     * Decodifica el primer código de barras encontrado en un File (foto subida).
     * @param {File} file - archivo de imagen
     * @returns {Promise<string>} texto del código de barras
     * @throws {Error} si no se detecta ningún código
     */
    async function decodeFromFile(file) {
        const url = URL.createObjectURL(file);
        try {
            const img = document.createElement('img');
            img.src = url;
            await new Promise((resolve, reject) => {
                img.onload = resolve;
                img.onerror = () => reject(new Error('No se pudo cargar la imagen'));
            });
            const result = await codeReader.decodeFromImageElement(img);
            return result.getText();
        } catch (err) {
            if (err.name === 'NotFoundException') {
                throw new Error('No se detectó ningún código de barras en la imagen');
            }
            throw err;
        } finally {
            URL.revokeObjectURL(url);
        }
    }

    /** Beep corto al escanear con éxito. Silencioso si el navegador bloquea AudioContext. */
    function _beep() {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.frequency.value = 880;
            gain.gain.setValueAtTime(0.3, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.15);
            osc.start(ctx.currentTime);
            osc.stop(ctx.currentTime + 0.15);
        } catch (_) {}
    }

    return { startCamera, stopCamera, decodeFromFile };
})();
