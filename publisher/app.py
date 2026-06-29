# FOR TEST PURPOSE
import sys
import importlib
sys.path.append("/home/kemot/Documents/Dev/MonkePipeline/publisher")
import collector
importlib.reload(collector)
import exporter
importlib.reload(exporter)


from collector import AssetsCollector
from exporter import UsdExporter



class MonkePublisher:
    def __init__(self):
        pass
    
    def publish(self):
        asset_collector = AssetsCollector()
        asset_collector.collect()
        usd_exporter = UsdExporter("/home/kemot/Documents/Dev/_TMP/TestMonkeOutput")
        for asset_item in asset_collector.items:
            usd_exporter.export(asset_item)
    

if __name__ == "__main__":
    monke_publisher = MonkePublisher()
    monke_publisher.publish()
