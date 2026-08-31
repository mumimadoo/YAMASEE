(function () {
    const canvas = document.getElementById('nightShaderCanvas');
    if (!canvas) return;

    let gl = null;
    let program = null;
    let animationFrameId = null;
    let startTime = Date.now();
    let isRunning = false;

    // Dithering Configuration
    const DITHER_DENSITY = 112.0;

    // Shader Presets System
    const SHADER_PRESETS = {
        SOFT: {
            scale: 1.60,
            intensity: 0.52,
            paramA: 0.45,
            warp: 0.035,
            detail: 1.60,
            contrast: 1.05,
            brightness: -0.01,
            saturation: 0.90,
            vignette: 0.08,
            blur: 0.0005,
            grain: 0.012,
            drift: 0.03,
            timeScale: 0.35
        },
        BALANCED: {
            scale: 1.85,
            intensity: 0.65,
            paramA: 0.50,
            warp: 0.05,
            detail: 1.80,
            contrast: 1.12,
            brightness: 0.00,
            saturation: 1.02,
            vignette: 0.12,
            blur: 0.001,
            grain: 0.015,
            drift: 0.045,
            timeScale: 0.45
        },
        BOLD: {
            scale: 2.10,
            intensity: 0.75,
            paramA: 0.58,
            warp: 0.08,
            detail: 2.10,
            contrast: 1.18,
            brightness: 0.02,
            saturation: 1.10,
            vignette: 0.16,
            blur: 0.002,
            grain: 0.022,
            drift: 0.06,
            timeScale: 0.55
        }
    };

    const ACTIVE_PRESET = 'BALANCED';
    const params = SHADER_PRESETS[ACTIVE_PRESET];

    // 1. Mobile Detection Fallback
    function isMobileDevice() {
        return (window.innerWidth <= 768) || 
               (/Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent));
    }

    // 2. WebGL Support Verification
    function initWebGL() {
        if (isMobileDevice()) {
            console.log("[ShaderBG] Mobile device detected. Using static CSS gradient fallback.");
            return false;
        }

        const glOptions = { alpha: false, depth: false, antialias: false, powerPreference: "low-power" };
        gl = canvas.getContext('webgl', glOptions) || canvas.getContext('experimental-webgl', glOptions);
        if (!gl) {
            console.warn("[ShaderBG] WebGL not supported on this browser.");
            return false;
        }
        return true;
    }

    // Shader Source Definitions
    const vsSource = `
        attribute vec2 position;
        varying vec2 v_uv;
        void main() {
            v_uv = position * 0.5 + 0.5;
            gl_Position = vec4(position, 0.0, 1.0);
        }
    `;

    const fsSource = `
        precision mediump float;
        uniform float u_time;
        uniform vec2 u_resolution;
        uniform float u_intensity;
        uniform float u_drift;
        uniform float u_contrast;
        uniform float u_grain;
        uniform float u_scale;
        uniform float u_paramA;
        uniform float u_warp;
        uniform float u_detail;
        uniform float u_brightness;
        uniform float u_saturation;
        uniform float u_vignette;
        uniform float u_blur;
        uniform float u_dither_density;

        float hash(vec2 p) {
            return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
        }

        float noise(vec2 p) {
            vec2 i = floor(p);
            vec2 f = fract(p);
            vec2 u = f * f * (3.0 - 2.0 * f);
            return mix(mix(hash(i + vec2(0.0,0.0)), hash(i + vec2(1.0,0.0)), u.x),
                       mix(hash(i + vec2(0.0,1.0)), hash(i + vec2(1.0,1.0)), u.x), u.y);
        }

        float fbm(vec2 p, float detail) {
            float val = 0.0;
            float amp = 0.5;
            float freq = 1.0;
            for (int i = 0; i < 3; i++) {
                val += amp * noise(p * freq);
                freq *= detail;
                amp *= 0.5;
            }
            return val;
        }

        float getBayer4x4(vec2 p) {
            int x = int(mod(p.x, 4.0));
            int y = int(mod(p.y, 4.0));
            if (y == 0) {
                if (x == 0) return 0.0/16.0;
                if (x == 1) return 8.0/16.0;
                if (x == 2) return 2.0/16.0;
                if (x == 3) return 10.0/16.0;
            }
            if (y == 1) {
                if (x == 0) return 12.0/16.0;
                if (x == 1) return 4.0/16.0;
                if (x == 2) return 14.0/16.0;
                if (x == 3) return 6.0/16.0;
            }
            if (y == 2) {
                if (x == 0) return 3.0/16.0;
                if (x == 1) return 11.0/16.0;
                if (x == 2) return 1.0/16.0;
                if (x == 3) return 9.0/16.0;
            }
            if (y == 3) {
                if (x == 0) return 15.0/16.0;
                if (x == 1) return 7.0/16.0;
                if (x == 2) return 13.0/16.0;
                if (x == 3) return 5.0/16.0;
            }
            return 0.0;
        }

        void main() {
            vec2 uv = gl_FragCoord.xy / u_resolution.xy;
            
            // Soft blur: mix pixel UV with quantized cell UV
            vec2 cellUV = floor(uv * u_dither_density) / u_dither_density;
            vec2 mixedUV = mix(cellUV, uv, u_blur);
            
            // Add vertical drift
            vec2 noiseUV = mixedUV * u_scale + vec2(0.0, u_time * u_drift);
            
            // Domain warp using FBM
            vec2 warp_offset = vec2(
                fbm(noiseUV + vec2(0.0, 1.0) * u_time * 0.1, u_detail), 
                fbm(noiseUV + vec2(1.0, 0.0) * u_time * 0.1, u_detail)
            );
            vec2 warpedUV = noiseUV + u_warp * warp_offset;
            
            // FBM Field value
            float val = fbm(warpedUV, u_detail);
            
            // Get bayer dither value
            float dither = getBayer4x4(gl_FragCoord.xy);
            
            // Apply dither and offset parameter A
            float quantized = val + (dither - 0.5) * u_intensity;
            float final_val = clamp(quantized + u_paramA - 0.5, 0.0, 1.0);
            
            // Define palette (Purple-Magenta retheme)
            vec3 col0 = vec3(0.03137, 0.02353, 0.06667); // #080611 - Dark Base
            vec3 col1 = vec3(0.09020, 0.06275, 0.16863); // #17102B - Deep Purple
            vec3 col2 = vec3(0.29412, 0.18039, 0.51373); // #4B2E83 - Royal Purple
            vec3 col3 = vec3(0.75686, 0.23529, 0.54118); // #C13C8A - Magenta
            vec3 col4 = vec3(0.95294, 0.54902, 0.79608); // #F38CCB - Soft Pink Highlight
            
            // Map quantized value to palette based on target visual distribution:
            // 50% col0, 25% col1, 15% col2, 8% col3, 2% col4
            vec3 col = col0;
            if (final_val < 0.50) {
                col = mix(col0, col1, smoothstep(0.40, 0.50, final_val));
            } else if (final_val < 0.75) {
                col = mix(col1, col2, smoothstep(0.65, 0.75, final_val));
            } else if (final_val < 0.90) {
                col = mix(col2, col3, smoothstep(0.80, 0.90, final_val));
            } else {
                col = mix(col3, col4, smoothstep(0.90, 0.98, final_val));
            }
            
            // Contrast
            col = pow(col, vec3(u_contrast));
            
            // Brightness
            col += vec3(u_brightness);
            
            // Saturation
            float luma = dot(col, vec3(0.299, 0.587, 0.114));
            col = mix(vec3(luma), col, u_saturation);
            
            // Vignette
            float d = length(uv - 0.5);
            col *= (1.0 - u_vignette * d * d);
            
            // Grain overlay
            float gVal = (hash(gl_FragCoord.xy + u_time) - 0.5) * u_grain;
            col += vec3(gVal);
            
            gl_FragColor = vec4(col, 1.0);
        }
    `;

    function loadShader(type, source) {
        const shader = gl.createShader(type);
        gl.shaderSource(shader, source);
        gl.compileShader(shader);
        if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
            console.error('[ShaderBG] Compile error:', gl.getShaderInfoLog(shader));
            gl.deleteShader(shader);
            return null;
        }
        return shader;
    }

    function initShaderProgram() {
        const vs = loadShader(gl.VERTEX_SHADER, vsSource);
        const fs = loadShader(gl.FRAGMENT_SHADER, fsSource);
        if (!vs || !fs) return false;

        program = gl.createProgram();
        gl.attachShader(program, vs);
        gl.attachShader(program, fs);
        gl.linkProgram(program);

        if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
            console.error('[ShaderBG] Link error:', gl.getProgramInfoLog(program));
            return false;
        }
        gl.useProgram(program);
        return true;
    }

    function setupGeometry() {
        const vertices = new Float32Array([
            -1.0, -1.0,
             1.0, -1.0,
            -1.0,  1.0,
            -1.0,  1.0,
             1.0, -1.0,
             1.0,  1.0
        ]);
        const buffer = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
        gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.STATIC_DRAW);

        const positionLocation = gl.getAttribLocation(program, 'position');
        gl.enableVertexAttribArray(positionLocation);
        gl.vertexAttribPointer(positionLocation, 2, gl.FLOAT, false, 0, 0);
    }

    function resizeCanvas() {
        const dpr = window.devicePixelRatio || 1;
        const width = window.innerWidth;
        const height = window.innerHeight;
        if (canvas.width !== width || canvas.height !== height) {
            canvas.width = width * dpr;
            canvas.height = height * dpr;
            gl.viewport(0, 0, canvas.width, canvas.height);
        }
    }

    // Rendering loop
    function render() {
        if (!isRunning) return;

        // Check theme status
        const isNight = document.documentElement.getAttribute('data-theme') === 'night';
        if (!isNight) {
            stopLoop();
            return;
        }

        resizeCanvas();

        const timeInSeconds = ((Date.now() - startTime) / 1000.0) * params.timeScale;

        // Bind Uniforms
        gl.uniform1f(gl.getUniformLocation(program, 'u_time'), timeInSeconds);
        gl.uniform2f(gl.getUniformLocation(program, 'u_resolution'), canvas.width, canvas.height);
        gl.uniform1f(gl.getUniformLocation(program, 'u_intensity'), params.intensity);
        gl.uniform1f(gl.getUniformLocation(program, 'u_drift'), params.drift);
        gl.uniform1f(gl.getUniformLocation(program, 'u_contrast'), params.contrast);
        gl.uniform1f(gl.getUniformLocation(program, 'u_grain'), params.grain);
        gl.uniform1f(gl.getUniformLocation(program, 'u_scale'), params.scale);
        gl.uniform1f(gl.getUniformLocation(program, 'u_paramA'), params.paramA);
        gl.uniform1f(gl.getUniformLocation(program, 'u_warp'), params.warp);
        gl.uniform1f(gl.getUniformLocation(program, 'u_detail'), params.detail);
        gl.uniform1f(gl.getUniformLocation(program, 'u_brightness'), params.brightness);
        gl.uniform1f(gl.getUniformLocation(program, 'u_saturation'), params.saturation);
        gl.uniform1f(gl.getUniformLocation(program, 'u_vignette'), params.vignette);
        gl.uniform1f(gl.getUniformLocation(program, 'u_blur'), params.blur);
        gl.uniform1f(gl.getUniformLocation(program, 'u_dither_density'), DITHER_DENSITY);

        gl.clearColor(0.0, 0.0, 0.0, 1.0);
        gl.clear(gl.COLOR_BUFFER_BIT);
        gl.drawArrays(gl.TRIANGLES, 0, 6);

        // Respect prefers-reduced-motion
        const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        if (prefersReducedMotion) {
            console.log("[ShaderBG] prefers-reduced-motion detected. Drawing static frame and pausing animation loop.");
            isRunning = false;
            return;
        }

        animationFrameId = requestAnimationFrame(render);
    }

    function startLoop() {
        if (isRunning) return;
        const isNight = document.documentElement.getAttribute('data-theme') === 'night';
        if (!isNight) return;

        isRunning = true;
        render();
    }

    function stopLoop() {
        isRunning = false;
        if (animationFrameId) {
            cancelAnimationFrame(animationFrameId);
            animationFrameId = null;
        }
    }

    // Visibility observer to optimize CPU usage
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            stopLoop();
        } else {
            startLoop();
        }
    });

    window.addEventListener('resize', () => {
        if (isRunning) {
            resizeCanvas();
        }
    });

    // Theme switch listener
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.type === 'attributes' && mutation.attributeName === 'data-theme') {
                const currentTheme = document.documentElement.getAttribute('data-theme');
                if (currentTheme === 'night') {
                    startLoop();
                } else {
                    stopLoop();
                }
            }
        });
    });
    observer.observe(document.documentElement, { attributes: true });

    // Initializer
    if (initWebGL() && initShaderProgram()) {
        setupGeometry();
        startLoop();
    }
})();
