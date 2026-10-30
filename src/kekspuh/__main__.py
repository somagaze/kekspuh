import time

from kekspuh import endpoint_ingest


def main() -> None:
    while True:
        endpoint_ingest.main()
        sleep: int = 10
        print(f" Sleeping for {sleep} seconds...")
        time.sleep(sleep)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!STOPPED!] by User.")
