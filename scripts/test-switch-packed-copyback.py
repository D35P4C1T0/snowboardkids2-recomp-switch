#!/usr/bin/env python3
"""Execute the production copy shader and verify its native byte representation."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
base = root / 'build-switch-deps/rt64/src'
formats = (base/'shaders/Formats.hlsli').read_text()
depth = (base/'shaders/Depth.hlsli').read_text()
random = (base/'shaders/Random.hlsli').read_text()
shader = (base/'shaders/SwitchFramebufferColorCopyPS.hlsl').read_text()
# Only HLSL syntax/interface adapters are replaced; the math and PS body are
# taken verbatim from production. DXC separately compiles the real GPU shader.
functions = formats[formats.index('static const uint DitherPatternBayer'):formats.index('uint AlphaDitherValue')]
functions += formats[formats.index('float4 RGBA16ToFloat4'):formats.index('float4 IA16ToFloat4')]
functions += depth[depth.index('#define DEPTH_EXPONENT_MASK'):depth.index('float Depth16ToFloat')]
functions += random[random.index('uint initRand'):random.index('void nextRandUint')].replace('[unroll]', '')
functions += shader[shader.index('float4 PSMain'):].replace('in float4', 'float4').replace('in float2', 'float2').replace(' : SV_Position','').replace(' : TEXCOORD0','').replace(' : SV_TARGET','')
functions = functions.replace('round(', 'hlslRound(').replace('hlslRound(i.a * cvgRange) % 8', 'int(hlslRound(i.a * cvgRange)) % 8')
stub = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
using uint = uint32_t;
using std::min; using std::clamp;
uint min(uint x, int y) { return std::min(x,uint(y)); }
uint clamp(uint x, int lo, int hi) { return std::clamp(x,uint(lo),uint(hi)); }
float hlslRound(float x) { return std::nearbyint(x); }
int firstbithigh(uint x) { return x ? 31-__builtin_clz(x) : -1; }
struct float2 { float x,y; };
struct uint2 { uint x,y; explicit uint2(float2 v):x(v.x),y(v.y){} };
struct uint3 { uint2 xy; uint z; uint3(uint2 v,uint w):xy(v),z(w){} };
struct float4 {
    float r,g,b,a; float2 xy;
    float4(float x,float y,float z,float w):r(x),g(y),b(z),a(w),xy{x,y}{}
};
struct { uint rowWidth=320,ditherPattern=3,ditherRandomSeed=0x12345,usesHDR=0,depth=0; } gConstants;
struct { float4 value{0,0,0,0}; float4 Load(uint3) { return value; } } gInput;
'''
test = r'''
uint byte(float x) { return uint(hlslRound(clamp(x,0.0f,1.0f)*255.0f)); }
uint result(float4 x) { return (byte(x.r)<<8)|byte(x.g); }
int main() {
    // Every possible native color must survive RG8 quantization unchanged.
    // Depth values have their two dz bits zero for FloatToDepth16(z,0).
    for(uint value=0;value<65536;value++) {
        float4 encoded(float(value>>8)/255.0f,float(value&255)/255.0f,0,1);
        assert(result(encoded)==value);
        assert(Float4ToRGBA16(RGBA16ToFloat4(value),0,false)==value);
    }
    gConstants.depth=1;
    // Exhaust the 18-bit fixed depth range through the production pixel shader,
    // comparing with the previous GPU RGBA8 -> CPU RGBA16 round trip.
    for(uint fixed=0;fixed<262144;fixed++) {
        float z=float(fixed)/262143.0f;
        uint value=FloatToDepth16(z,0.0f);
        float4 oldColor=RGBA16ToFloat4(value);
        float4 quantized(float(byte(oldColor.r))/255.0f,float(byte(oldColor.g))/255.0f,
                         float(byte(oldColor.b))/255.0f,float(byte(oldColor.a))/255.0f);
        uint reference=Float4ToRGBA16(quantized,0,false);
        gInput.value=float4(z,0,0,1);
        assert(result(PSMain(float4(7.5f,21.5f,0,1),float2{0,0}))==reference);
    }
    gConstants.depth=0;
    for(uint hdr:{0U,1U}) for(uint pattern=0;pattern<4;pattern++)
    for(uint y:{0U,7U,21U}) for(uint x=0;x<320;x++) {
        gConstants.usesHDR=hdr; gConstants.ditherPattern=pattern;
        gInput.value=float4(float((x*37+y)&255)/255.0f,float((x*19+y)&255)/255.0f,
                           float((x*7+y)&255)/255.0f,float((x+y)&255)/255.0f);
        uint2 coord(float2{float(x),float(y)});
        uint seed=pattern==2 ? initRand(gConstants.ditherRandomSeed,y*320+x,16) : 0;
        uint reference=Float4ToRGBA16(gInput.value,DitherPatternValue(pattern,coord,seed),hdr!=0);
        assert(result(PSMain(float4(float(x)+0.5f,float(y)+0.5f,0,1),float2{0,0}))==reference);
    }
}
'''
with tempfile.TemporaryDirectory(prefix='sk2-packed-shader-') as temp:
    src=Path(temp)/'test.cpp'; exe=Path(temp)/'test'
    src.write_text(stub+functions+test)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++17','-O2','-Wall','-Wextra','-Werror',
                    '-Wno-unused-parameter',str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('PASS: production pixel shader, 65536 native words, 262144 depth values, color/HDR dithering and row offsets')
