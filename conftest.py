def pytest_addoption(parser):
    parser.addoption(
        '--runcombat',
        action='store_true',
        default=False,
        help='Run tests in combat conditions'
    )
    parser.addoption(
        '--runpaid',
        action='store_true',
        default=False,
        help='Run paid tests'
    )
