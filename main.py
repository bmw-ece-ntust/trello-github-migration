from src.controllers.main_application import MainApplication


def main():
    app = MainApplication()
    app.run(board_name="internship")


if __name__ == "__main__":
    main()
