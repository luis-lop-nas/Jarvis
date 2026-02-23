import Metal
import MetalKit
import simd

// ── Uniform block (must match MSL struct byte-for-byte) ───────────────────────

struct Uniforms {
    var resolution: SIMD2<Float>    //  0..7   (8-byte aligned)
    var time:       Float           //  8..11
    var pad:        Float = 0       // 12..15
}   // 16 bytes

// ── Renderer ──────────────────────────────────────────────────────────────────

final class Renderer: NSObject, MTKViewDelegate {

    private let device:   MTLDevice
    private let queue:    MTLCommandQueue
    private var pipeline: MTLRenderPipelineState!
    private var pbuf:     MTLBuffer!    // GPU particle data
    private var ubuf:     MTLBuffer!    // Uniforms

    let particles: ParticleSystem

    private var t:        Float          = 0
    private var lastTime: CFAbsoluteTime = 0

    // MARK: - Init

    init(device: MTLDevice, logicalSize: CGSize) {
        self.device = device
        self.queue  = device.makeCommandQueue()!

        let cx = Float(logicalSize.width)  / 2
        let cy = Float(logicalSize.height) / 2
        self.particles = ParticleSystem(centerX: cx, centerY: cy)

        super.init()
        buildPipeline()
        allocBuffers()
        lastTime = CFAbsoluteTimeGetCurrent()
    }

    // MARK: - Setup

    private func buildPipeline() {
        guard let lib = try? device.makeLibrary(source: kMetalSource, options: nil) else {
            fatalError("Metal shader compilation failed — check MSL source")
        }
        guard let vert = lib.makeFunction(name: "particleVert"),
              let frag = lib.makeFunction(name: "particleFrag") else {
            fatalError("Metal functions not found in shader source")
        }

        let desc = MTLRenderPipelineDescriptor()
        desc.vertexFunction   = vert
        desc.fragmentFunction = frag
        desc.colorAttachments[0].pixelFormat = .bgra8Unorm

        // Pre-multiplied alpha source-over blending
        // Particles output pre-multiplied RGBA; the OS composites over the desktop
        let att = desc.colorAttachments[0]!
        att.isBlendingEnabled           = true
        att.sourceRGBBlendFactor        = .one
        att.destinationRGBBlendFactor   = .oneMinusSourceAlpha
        att.sourceAlphaBlendFactor      = .one
        att.destinationAlphaBlendFactor = .oneMinusSourceAlpha

        pipeline = try! device.makeRenderPipelineState(descriptor: desc)
    }

    private func allocBuffers() {
        pbuf = device.makeBuffer(
            length:  particles.count * MemoryLayout<GPUParticle>.stride,
            options: .storageModeShared
        )
        ubuf = device.makeBuffer(
            length:  MemoryLayout<Uniforms>.stride,
            options: .storageModeShared
        )
    }

    // MARK: - MTKViewDelegate

    func mtkView(_ view: MTKView, drawableSizeWillChange size: CGSize) {
        // Drawable size changed (Space transition, display config change)
        // Particle positions are in logical points; no action needed here
    }

    func draw(in view: MTKView) {
        let now = CFAbsoluteTimeGetCurrent()
        let dt  = Float(min(now - lastTime, 1.0 / 20.0))   // cap at 20fps worth
        lastTime = now
        t += dt

        particles.update(dt: dt)

        guard let drawable = view.currentDrawable,
              let rpd      = view.currentRenderPassDescriptor,
              let cmd      = queue.makeCommandBuffer() else { return }

        // ── Upload particle data ───────────────────────────────────────────────
        let pptr = pbuf.contents().bindMemory(
            to: GPUParticle.self, capacity: particles.count)
        for i in 0..<particles.count { pptr[i] = particles.gpuData[i] }

        // ── Upload uniforms (use logical bounds for coordinate matching) ───────
        let sz  = view.bounds.size
        var uni = Uniforms(
            resolution: SIMD2(Float(sz.width), Float(sz.height)),
            time: t
        )
        memcpy(ubuf.contents(), &uni, MemoryLayout<Uniforms>.stride)

        // ── Render pass (clear to fully transparent) ──────────────────────────
        rpd.colorAttachments[0].clearColor  = MTLClearColorMake(0, 0, 0, 0)
        rpd.colorAttachments[0].loadAction  = .clear
        rpd.colorAttachments[0].storeAction = .store

        guard let enc = cmd.makeRenderCommandEncoder(descriptor: rpd) else { return }
        enc.setRenderPipelineState(pipeline)
        enc.setVertexBuffer(pbuf, offset: 0, index: 0)
        enc.setVertexBuffer(ubuf,  offset: 0, index: 1)
        enc.drawPrimitives(type: .point, vertexStart: 0, vertexCount: particles.count)
        enc.endEncoding()

        cmd.present(drawable)
        cmd.commit()
    }
}

// ── MSL Shader source ─────────────────────────────────────────────────────────
//   Compiled at runtime via makeLibrary(source:) — no .metal file needed.

private let kMetalSource = """
#include <metal_stdlib>
using namespace metal;

// ── Data structures (mirror Swift layout exactly) ─────────────────────────────

struct GPUParticle {
    float x, y;        //  0..7
    float r, g, b, a;  //  8..23
    float size;        // 24..27
    float pad;         // 28..31
};

struct Uniforms {
    float2 resolution; //  0..7
    float  time;       //  8..11
    float  pad;        // 12..15
};

struct V2F {
    float4 position  [[position]];
    float4 color;
    float  pointSize [[point_size]];
};

// ── Vertex: logical screen coords → NDC ───────────────────────────────────────
// AppKit origin: bottom-left, Y-up — matches Metal NDC direction, so no Y-flip.

vertex V2F particleVert(
    uint                  vid   [[vertex_id]],
    constant GPUParticle* parts [[buffer(0)]],
    constant Uniforms&    uni   [[buffer(1)]]
) {
    GPUParticle p = parts[vid];

    float2 ndc = float2(
        p.x / uni.resolution.x * 2.0 - 1.0,
        p.y / uni.resolution.y * 2.0 - 1.0
    );

    V2F out;
    out.position  = float4(ndc, 0.0, 1.0);
    out.color     = float4(p.r, p.g, p.b, p.a);
    out.pointSize = p.size * 5.5;   // physical pixels
    return out;
}

// ── Fragment: layered glow disk, outputs pre-multiplied RGBA ──────────────────

fragment float4 particleFrag(
    V2F    in         [[stage_in]],
    float2 pointCoord [[point_coord]])
{
    // pointCoord: (0,0)=top-left, (1,1)=bottom-right of the point sprite
    float2 uv   = pointCoord * 2.0 - 1.0;
    float  d    = length(uv);
    if (d > 1.0) discard_fragment();

    // Bright pin-point core + soft outer halo
    float core  = pow(1.0 - saturate(d * 1.7), 5.0);
    float halo  = pow(1.0 - saturate(d),       1.3) * 0.5;
    float glow  = saturate(core + halo);

    float  alpha = glow * in.color.a;
    float3 rgb   = in.color.rgb * alpha;    // pre-multiply for correct blending
    return float4(rgb, alpha);
}
"""
