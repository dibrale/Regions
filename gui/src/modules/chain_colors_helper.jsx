import {CHAIN_COLORS} from "@/modules/chain_colors.jsx";

export function ChainColors(chainColors, selectedLayer, newLayerConfig, chainName, setChainColors) {
    const newChainColors = [...chainColors];
    if (!newChainColors[selectedLayer]) {
        newChainColors[selectedLayer] = {};
    }
    const existingChainCount = Object.keys(newLayerConfig[selectedLayer]).length - 1;
    newChainColors[selectedLayer][chainName] = existingChainCount % CHAIN_COLORS.length;
    setChainColors(newChainColors);
}