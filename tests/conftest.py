import os
os.environ["DATABASE_URL"]="sqlite:///./test_bankdq.db"
os.environ["JWT_SECRET"]="test-secret-key-for-unit-tests"
