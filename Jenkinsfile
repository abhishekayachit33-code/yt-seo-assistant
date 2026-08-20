pipeline {
    agent any

    environment {
        DOCKERHUB_USERNAME = 'abhishekayachit'
        IMAGE_NAME         = "${DOCKERHUB_USERNAME}/yt-seo-assistant"
        API_IMAGE          = "${DOCKERHUB_USERNAME}/yt-seo-api"
        WEB_IMAGE          = "${DOCKERHUB_USERNAME}/yt-seo-web"
        // Baked into the web bundle at build time (NEXT_PUBLIC_* is inlined
        // by Next.js, not read at runtime), so it belongs here rather than
        // in the deployment manifest.
        PUBLIC_API_URL     = 'http://ytseo.local/api/v1'
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

                    # API image builds from the REPO ROOT, not backend/: it
                    # imports the pipeline modules that live there, so
                    # backend/ alone yields an image that fails on first
                    # import.
                    docker build -f backend/Dockerfile \
                        -t ${API_IMAGE}:${SHORT_SHA} -t ${API_IMAGE}:latest .

                    docker build -f frontend/Dockerfile \
                        --build-arg NEXT_PUBLIC_API_URL=${PUBLIC_API_URL} \
                        -t ${WEB_IMAGE}:${SHORT_SHA} -t ${WEB_IMAGE}:latest frontend
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
                        docker push ${API_IMAGE}:${SHORT_SHA}
                        docker push ${API_IMAGE}:latest
                        docker push ${WEB_IMAGE}:${SHORT_SHA}
                        docker push ${WEB_IMAGE}:latest
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
                        # No -i '' here: Jenkins runs on Linux, where GNU
                        # sed reads '' as the next script argument and fails.
                        # The BSD form only works on the macOS dev box.
                        sed -i "s|image: docker.io/${IMAGE_NAME}:.*|image: docker.io/${IMAGE_NAME}:${SHORT_SHA}|" manifests/deployment.yaml
                        sed -i "s|image: docker.io/${API_IMAGE}:.*|image: docker.io/${API_IMAGE}:${SHORT_SHA}|" manifests/api-deployment.yaml
                        sed -i "s|image: docker.io/${WEB_IMAGE}:.*|image: docker.io/${WEB_IMAGE}:${SHORT_SHA}|" manifests/web-deployment.yaml
                        git add manifests/deployment.yaml manifests/api-deployment.yaml manifests/web-deployment.yaml
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
