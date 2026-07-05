with open('requirements.txt', 'r') as f:
    lines = [line.strip() for line in f.readlines()]

test_deps = [
    "pytest==8.3.2",
    "pytest-asyncio==0.24.0",
    "pytest-mock==3.14.0"
]

existing = {line.split('==')[0].lower() for line in lines if '==' in line}
new_deps = [dep for dep in test_deps if dep.split('==')[0].lower() not in existing]

if new_deps:
    with open('requirements.txt', 'a') as f:
        f.write("\n# Test dependencies\n")
        for dep in new_deps:
            f.write(dep + "\n")
    print(f"✅ Добавлены зависимости: {new_deps}")
else:
    print("ℹ️ Все тестовые зависимости уже есть в requirements.txt")
