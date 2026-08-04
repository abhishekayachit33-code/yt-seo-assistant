pipeline {
    agent any

    environment {
        DOCKERHUB_USERNAME = 'abhishekayachit'
        IMAGE_NAME         = "${DOCKERHUB_USERNAME}/yt-seo-assistant"
        DEPLOY_REPO        = 'github.com/abhishekayachit33-code/yt-seo-assistant-deploy.git'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                script {
                    env.SHORT_SHA = sh(returnStdout: true, script: 'git rev-parse --short HEAD').trim()
                }
            }
        }

        stage('Test') {
            steps {
                sh '''
                    python3 -m venv .venv
                    . .venv/bin/activate
                    pip install -q -r requirements.txt -r requirements-dev.txt
                    pytest -q
                '''
            }
        }

        stage('Build') {
            steps {
                sh """
                    docker build -t ${IMAGE_NAME}:${SHORT_SHA} -t ${IMAGE_NAME}:latest .
                """
            }
        }

        stage('Push') {
            steps {
                withCredentials([usernamePassword(
                    credentialsId: 'dockerhub-creds',
                    usernameVariable: 'DOCKER_USER',
                    passwordVariable: 'DOCKER_PASS'
                )]) {
                    sh '''
                        echo "$DOCKER_PASS" | docker login -u "$DOCKER_USER" --password-stdin
                        docker push ${IMAGE_NAME}:${SHORT_SHA}
                        docker push ${IMAGE_NAME}:latest
                        docker logout
                    '''
                }
            }
        }

        stage('Update manifests') {
            steps {
                withCredentials([usernamePassword(
                    credentialsId: 'github-deploy-token',
                    usernameVariable: 'GIT_USER',
                    passwordVariable: 'GIT_TOKEN'
                )]) {
                    sh '''
                        rm -rf deploy-repo
                        git clone https://${GIT_USER}:${GIT_TOKEN}@${DEPLOY_REPO} deploy-repo
                        cd deploy-repo
                        git config user.email "jenkins@local"
                        git config user.name "Jenkins"
                        sed -i '' "s|image: docker.io/${IMAGE_NAME}:.*|image: docker.io/${IMAGE_NAME}:${SHORT_SHA}|" manifests/deployment.yaml
                        git add manifests/deployment.yaml
                        git commit -m "chore: deploy ${SHORT_SHA}"
                        git push https://${GIT_USER}:${GIT_TOKEN}@${DEPLOY_REPO} HEAD:main
                    '''
                }
            }
        }
    }

    post {
        always {
            sh 'docker image prune -f || true'
            cleanWs()
        }
    }
}
