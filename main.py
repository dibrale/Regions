import os
import asyncio

from modules.config import params
from modules.neural_region import NeuralRegion


# Main function that runs the script
async def main():


       return 0


if __name__ == "__main__":
    # Set environment variables
    os.environ["CUDA_VISIBLE_DEVICES"] = str(params['CUDA_VISIBLE_DEVICES'])

    #initialize region registry
    REGION_REGISTRY = {}

    # Enter the main event loop
    loop = asyncio.get_event_loop()
    asyncio.ensure_future(main())
    loop.run_forever()
