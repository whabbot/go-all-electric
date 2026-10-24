import type { PhotoKind } from '../api'

type Example = { src: string; alt: string }

// URLs do not fetch images until the dialog mounts its image elements.
export const CAPTURE_EXAMPLES: Record<PhotoKind, Record<'good' | 'bad', Example>> = {
  boiler_plate: {
    good: {
      src: new URL('../assets/capture-examples/boiler-good.webp', import.meta.url).href,
      alt: 'Sharp boiler data plate with model H24 and central heating output 24 kW visible.',
    },
    bad: {
      src: new URL('../assets/capture-examples/boiler-bad.webp', import.meta.url).href,
      alt: 'Boiler photographed from across the room; its tiny data plate cannot be read.',
    },
  },
  radiators: {
    good: {
      src: new URL('../assets/capture-examples/radiators-good.webp', import.meta.url).href,
      alt: 'Radiator photographed from a front corner looking down at about 45 degrees so the front face, top grille and fins, and one end are visible, with a tape measure held across the width.',
    },
    bad: {
      src: new URL('../assets/capture-examples/radiators-bad.webp', import.meta.url).href,
      alt: 'Radiator photographed straight front-on where single and double panel radiators look alike and panel and fin counts cannot be read.',
    },
  },
  fuse_cutout: {
    good: {
      src: new URL('../assets/capture-examples/fuse-good.webp', import.meta.url).href,
      alt: 'Sealed service fuse carrier in close-up with an 80 A rating visible.',
    },
    bad: {
      src: new URL('../assets/capture-examples/fuse-bad.webp', import.meta.url).href,
      alt: 'Consumer unit with circuit breakers: the wrong subject, with no service fuse carrier visible.',
    },
  },
  outdoor_space: {
    good: {
      src: new URL('../assets/capture-examples/outdoor-good.webp', import.meta.url).href,
      alt: 'Proposed outdoor spot showing wall, window, paving depth, drainpipe and measuring tape.',
    },
    bad: {
      src: new URL('../assets/capture-examples/outdoor-bad.webp', import.meta.url).href,
      alt: 'Tight crop of brickwork and a sliver of paving hides available space and obstructions.',
    },
  },
  loft: {
    good: {
      src: new URL('../assets/capture-examples/loft-good.webp', import.meta.url).href,
      alt: 'Clearly lit insulation and timber joists, with a tape measure in the wool.',
    },
    bad: {
      src: new URL('../assets/capture-examples/loft-bad.webp', import.meta.url).href,
      alt: 'Boarded loft floor covered with boxes hides insulation and its depth.',
    },
  },
  gas_bill: {
    good: {
      src: new URL('../assets/capture-examples/bill-good.webp', import.meta.url).href,
      alt: 'Fictional gas statement showing 12,450 kWh used from 01 April 2025 to 31 March 2026.',
    },
    bad: {
      src: new URL('../assets/capture-examples/bill-bad.webp', import.meta.url).href,
      alt: 'Fictional bill cropped to monetary charges only, without kWh usage or period dates.',
    },
  },
}
