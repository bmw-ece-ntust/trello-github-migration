from src.controllers.main_application import MainApplication
import argparse


def main():
    parser = argparse.ArgumentParser(description="Run Trello backup + GitHub migration workflow")
    parser.add_argument("--board", default="internship", help="Board name filter used by backup and migration steps")
    args = parser.parse_args()

    app = MainApplication()
    app.run(board_name=args.board)


if __name__ == "__main__":
    main()
